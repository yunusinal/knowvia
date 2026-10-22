"""Compare follow-up retrieval strategies on doc2dial (IBM, CC BY 3.0).

Every user turn in doc2dial is annotated with the document spans that answer it, so this
measures retrieval only: does the query find the right document and the answering span?
The dataset is read from data/runtime/datasets/doc2dial (gitignored). Each indexed corpus is
cached under data/runtime/eval-cache so query experiments do not re-embed 149 documents.
The report stores IDs and metrics only, no document text.

Corpus variants:
  plain  chunks are embedded as they are (what the app does today)
  title  each chunk is embedded as "<document title>\\n<chunk>"; stored text is unchanged

Feng et al., "doc2dial: A Goal-Oriented Document-Grounded Dialogue Dataset", EMNLP 2020.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Base, Department, Document, Role, User, Visibility
from app.repositories.vector_store import VectorStore
from app.services.chat import retrieval_query
from app.services.embeddings import Embedder, get_embedder
from app.services.ingest import DuplicateDocumentError, ingest_document
from app.services.llm import LLMUnavailableError, get_llm
from app.services.prompt import HistoryTurn
from app.services.retrieval import retrieve
from scripts.followup_eval import PAUSE_SECONDS, _rewrite
from scripts.rag_eval import ROOT, _normalize_text, _rate

DATA_DIR = ROOT / "data" / "runtime" / "datasets" / "doc2dial"
CACHE_DIR = ROOT / "data" / "runtime" / "eval-cache"
RESULTS_DIR = ROOT / "eval" / "results"
SPAN_PREFIX_CHARS = 80  # span'ın başı bir chunk'ta geçiyorsa cevabın geçtiği parça bulunmuş sayılır
METRICS = ("doc_first", "doc_in_top5", "span_in_top5")
# (önceki tur sayısı, tur başına karakter); "h2_300" uygulamanın bugünkü retrieval_query'sidir.
HISTORY_WINDOWS = {"h2_150": (2, 150), "h2_300": (2, 300), "h2_600": (2, 600), "h4_300": (4, 300), "h6_300": (6, 300)}


class TitledEmbedder:
    """Parçayı vektöre çevirirken başına belge başlığını ekler; arama sorgusuna dokunmaz."""

    def __init__(self, inner: Embedder, title: str) -> None:
        self._inner = inner
        self._title = title

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._inner.embed_passages([f"{self._title}\n{text}" for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)

    def count_passage_tokens(self, text: str) -> int:
        # Başlık da modelin token sınırını tüketir; chunk'lar buna göre küçülür.
        return self._inner.count_passage_tokens(f"{self._title}\n{text}")


def load_domain(domain: str) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    documents = json.loads((DATA_DIR / "doc2dial_doc.json").read_text(encoding="utf-8"))["doc_data"][domain]
    dialogues = json.loads((DATA_DIR / "doc2dial_dial_validation.json").read_text(encoding="utf-8"))
    return documents, [dialogue for group in dialogues["dial_data"][domain].values() for dialogue in group]


def follow_up_turns(dialogues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Önceki kullanıcı turu olan ve cevap parçası etiketlenmiş her kullanıcı turu bir örnektir."""
    samples = []
    for dialogue in dialogues:
        history: list[HistoryTurn] = []
        for turn in dialogue["turns"]:
            if turn["role"] == "user" and turn["references"] and any(t.role == "user" for t in history):
                samples.append({
                    "dial_id": dialogue["dial_id"], "turn_id": turn["turn_id"], "doc_id": dialogue["doc_id"],
                    "question": turn["utterance"], "history": list(history),
                    "span_ids": [reference["sp_id"] for reference in turn["references"]],
                })
            history.append(HistoryTurn("user" if turn["role"] == "user" else "assistant", turn["utterance"]))
    return samples


def _clean_title(title: str) -> str:
    return re.sub(r"#\d+$", "", title).strip()  # "Registrations#3" → "Registrations"


def open_corpus(
    domain: str, corpus: str, documents: dict[str, dict[str, Any]], embedder: Embedder,
) -> tuple[Session, VectorStore, User, dict[str, str], int | None]:
    """Önbellekteki korpusu açar; yoksa veya yarımsa baştan kurar. Dönüş: belge id → doc2dial id."""
    folder = CACHE_DIR / f"doc2dial-{domain}-{corpus}"
    ready = folder / "ready.json"
    if folder.exists() and not ready.exists():
        shutil.rmtree(folder)  # önceki kurulum yarıda kalmış; yarım korpusla ölçüm yapılmaz
    folder.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{folder / 'eval.db'}")
    Base.metadata.create_all(engine)
    db = Session(engine)
    store = VectorStore(QdrantClient(path=str(folder / "qdrant")), "doc2dial", embedder.dimension)
    store.ensure_collection()
    doc_ids = list(documents)

    ingest_seconds: int | None = None
    if not ready.exists():
        settings = get_settings()
        user = User(email="it@demo.local", password_hash="unused", role=Role.MEMBER, department=Department.IT)
        db.add(user)
        db.flush()
        started = time.perf_counter()
        for index, doc_id in enumerate(doc_ids):
            document = documents[doc_id]
            chunk_embedder = TitledEmbedder(embedder, _clean_title(document["title"])) if corpus == "title" else embedder
            try:
                ingest_document(
                    db, store, chunk_embedder, filename=f"{domain}-{index:04d}.txt",
                    content=document["doc_text"].encode("utf-8"),
                    department=Department.IT, visibility=Visibility.COMPANY,
                    uploaded_by=user.id, max_mb=settings.max_upload_mb,
                )
            except DuplicateDocumentError:
                continue  # aynı metne sahip ikinci belge; ilk kopya korpusta zaten var
        ingest_seconds = round(time.perf_counter() - started)
        ready.write_text(json.dumps({"ingest_seconds": ingest_seconds}), encoding="utf-8")

    user = db.scalars(select(User)).one()
    # Dosya adındaki sıra numarası doc2dial kimliğine geri çevrilir.
    mapping = {
        document.id: doc_ids[int(document.filename_original.rsplit("-", 1)[1].split(".")[0])]
        for document in db.scalars(select(Document))
    }
    return db, store, user, mapping, ingest_seconds


def queries_for(sample: dict[str, Any], llm: Any | None) -> dict[str, str]:
    question, history = sample["question"], sample["history"]
    previous_questions = [turn.content for turn in history if turn.role == "user"]
    queries = {"question_only": question, "previous_question": f"{question}\n{previous_questions[-1]}"}
    for name, (turns, chars) in HISTORY_WINDOWS.items():
        context = "\n".join(turn.content[:chars] for turn in history[-turns:])
        queries[name] = f"{question}\n{context}"
    # Deney ile uygulamanın aynı sorguyu kurduğunu garanti eder.
    assert queries["h2_300"] == retrieval_query(question, history)
    if llm is not None:
        queries["llm_rewrite"] = _rewrite(llm, question, history)
    return queries


def evaluate(
    db: Session, store: VectorStore, embedder: Embedder, user: User, mapping: dict[str, str],
    documents: dict[str, dict[str, Any]], samples: list[dict[str, Any]], rewrite_ids: set[int], llm: Any | None,
) -> tuple[list[dict[str, Any]], int]:
    settings = get_settings()
    rows, rewrite_failures = [], 0
    for sample in samples:
        document = documents[sample["doc_id"]]
        span_prefixes = [
            _normalize_text(document["spans"][span_id]["text_sp"])[:SPAN_PREFIX_CHARS]
            for span_id in sample["span_ids"]
        ]
        rewrite = llm is not None and id(sample) in rewrite_ids
        try:
            queries = queries_for(sample, llm if rewrite else None)
        except LLMUnavailableError:
            rewrite_failures += 1  # sağlayıcı hatası tüm ölçümü kaybettirmesin
            queries = queries_for(sample, None)
        if rewrite:
            time.sleep(PAUSE_SECONDS / 4)  # kısa çağrı; Groq dakika sınırına takılmamak için
        row: dict[str, Any] = {"dial_id": sample["dial_id"], "turn_id": sample["turn_id"]}
        for name, query in queries.items():
            hits = retrieve(db, store, embedder, user, query, settings.retrieval_top_k)
            hit_docs = [mapping.get(hit.document_id) for hit in hits]
            row[name] = {
                "doc_first": bool(hit_docs) and hit_docs[0] == sample["doc_id"],
                "doc_in_top5": sample["doc_id"] in hit_docs,
                "span_in_top5": any(
                    prefix and prefix in _normalize_text(hit.text)
                    for prefix in span_prefixes for hit, hit_doc in zip(hits, hit_docs, strict=True)
                    if hit_doc == sample["doc_id"]
                ),
                "top_score": round(hits[0].score, 4) if hits else None,
            }
        rows.append(row)
    return rows, rewrite_failures


def summarize(rows: list[dict[str, Any]], min_score: float) -> dict[str, Any]:
    strategies = sorted({key for row in rows for key in row if isinstance(row[key], dict)})
    summary: dict[str, Any] = {}
    for strategy in strategies:
        subset = [row[strategy] for row in rows if strategy in row]
        summary[strategy] = {metric: _rate([item[metric] for item in subset]) for metric in METRICS}
        summary[strategy]["top_score_below_threshold"] = sum(
            item["top_score"] is None or item["top_score"] < min_score for item in subset
        )
    return summary


def run(domain: str, corpus: str, rewrite_sample: int, seed: int) -> dict[str, Any]:
    settings = get_settings()
    documents, dialogues = load_domain(domain)
    samples = follow_up_turns(dialogues)
    rewrite_ids = {id(sample) for sample in random.Random(seed).sample(samples, min(rewrite_sample, len(samples)))}
    embedder = get_embedder()
    db, store, user, mapping, ingest_seconds = open_corpus(domain, corpus, documents, embedder)
    try:
        llm = get_llm() if rewrite_sample else None
        rows, rewrite_failures = evaluate(db, store, embedder, user, mapping, documents, samples, rewrite_ids, llm)
    finally:
        db.close()
        store.close()

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": "doc2dial v1.0.1 validation (IBM, CC BY 3.0)",
        "domain": domain,
        "corpus": corpus,
        "embedding_model": settings.embedding_model,
        "llm_model_for_rewrite": settings.llm_model if rewrite_sample else None,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_min_score": settings.retrieval_min_score,
        "corpus_documents": len(mapping),
        "ingest_seconds": ingest_seconds,  # None: önbellekten açıldı
        "follow_up_turns": len(rows),
        "rewrite_sample_turns": sum("llm_rewrite" in row for row in rows),
        "rewrite_failures": rewrite_failures,
        "history_windows": {name: {"turns": t, "chars": c} for name, (t, c) in HISTORY_WINDOWS.items()},
        "metrics": summarize(rows, settings.retrieval_min_score),
        "results": rows,
    }
    output = RESULTS_DIR / f"doc2dial-{domain}-{corpus}-{datetime.now(UTC).date().isoformat()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "results"}
    print(json.dumps({"output": str(output), **summary}, ensure_ascii=False, indent=2))
    return report


RERANKER = "onnx-community/bge-reranker-v2-m3-ONNX"  # BAAI/bge-reranker-v2-m3 (Apache-2.0), çok dilli


def load_reranker() -> Any:
    from fastembed.common.model_description import ModelSource
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    TextCrossEncoder.add_custom_model(
        model=RERANKER, sources=ModelSource(hf=RERANKER), model_file="onnx/model_int8.onnx",
        description="bge-reranker-v2-m3, int8 ONNX", license="apache-2.0", size_in_gb=0.57,
    )
    return TextCrossEncoder(RERANKER, cache_dir=get_settings().model_cache_dir)


def run_rerank(domain: str, corpus: str, sample_size: int, candidates: int, seed: int) -> dict[str, Any]:
    """Bugünkü sorguyla ilk `candidates` adayı alır, çapraz kodlayıcıyla yeniden sıralar ve ilk 5'i ölçer."""
    settings = get_settings()
    documents, dialogues = load_domain(domain)
    samples = random.Random(seed).sample(follow_up_turns(dialogues), sample_size)
    embedder = get_embedder()
    reranker = load_reranker()
    db, store, user, mapping, _ = open_corpus(domain, corpus, documents, embedder)
    rows, rerank_ms = [], []
    try:
        for sample in samples:
            document = documents[sample["doc_id"]]
            prefixes = [
                _normalize_text(document["spans"][span_id]["text_sp"])[:SPAN_PREFIX_CHARS]
                for span_id in sample["span_ids"]
            ]
            query = retrieval_query(sample["question"], sample["history"])
            hits = retrieve(db, store, embedder, user, query, candidates)
            started = time.perf_counter()
            scores = list(reranker.rerank(query, [hit.text for hit in hits]))
            rerank_ms.append(round((time.perf_counter() - started) * 1000))
            reranked = [hit for _, hit in sorted(zip(scores, hits, strict=True), key=lambda pair: -pair[0])]
            row: dict[str, Any] = {"dial_id": sample["dial_id"], "turn_id": sample["turn_id"]}
            for name, ranked in (("h2_300", hits), ("h2_300_rerank", reranked)):
                top = ranked[: settings.retrieval_top_k]
                hit_docs = [mapping.get(hit.document_id) for hit in top]
                row[name] = {
                    "doc_first": bool(hit_docs) and hit_docs[0] == sample["doc_id"],
                    "doc_in_top5": sample["doc_id"] in hit_docs,
                    "span_in_top5": any(
                        prefix and prefix in _normalize_text(hit.text)
                        for prefix in prefixes for hit, hit_doc in zip(top, hit_docs, strict=True)
                        if hit_doc == sample["doc_id"]
                    ),
                    "top_score": round(top[0].score, 4) if top else None,
                }
            row["doc_in_candidates"] = sample["doc_id"] in [mapping.get(hit.document_id) for hit in hits]
            rows.append(row)
    finally:
        db.close()
        store.close()

    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": "doc2dial v1.0.1 validation (IBM, CC BY 3.0)",
        "domain": domain, "corpus": corpus, "embedding_model": settings.embedding_model,
        "reranker": f"{RERANKER} (onnx/model_int8.onnx)", "candidates": candidates,
        "sample_turns": len(rows), "seed": seed,
        "metrics": summarize(rows, settings.retrieval_min_score),
        "doc_in_candidates": _rate([row["doc_in_candidates"] for row in rows]),
        "rerank_ms": {"mean": round(sum(rerank_ms) / len(rerank_ms)), "max": max(rerank_ms)},
        "results": rows,
    }
    output = RESULTS_DIR / f"doc2dial-{domain}-{corpus}-rerank-{datetime.now(UTC).date().isoformat()}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **{k: v for k, v in report.items() if k != "results"}}, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", default="dmv", choices=["dmv", "ssa", "va", "studentaid"])
    parser.add_argument("--corpus", default="plain", choices=["plain", "title"])
    parser.add_argument("--rewrite-sample", type=int, default=0, help="LLM ile yeniden yazılacak tur sayısı (0 = kapalı)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--rerank-sample", type=int, default=0, help="Yeniden sıralama deneyi için tur sayısı (0 = kapalı)")
    parser.add_argument("--candidates", type=int, default=20, help="Yeniden sıralanacak aday sayısı")
    args = parser.parse_args()
    if args.rerank_sample:
        run_rerank(args.domain, args.corpus, args.rerank_sample, args.candidates, args.seed)
    else:
        run(args.domain, args.corpus, args.rewrite_sample, args.seed)


if __name__ == "__main__":
    main()
