"""Compare dense, BM25 and hybrid retrieval on the Turkish demo corpus (retrieval only, no LLM calls).

The corpus is indexed through the real upload path into an in-memory SQLite and Qdrant, then copied
into a collection with named dense and BM25 (Turkish stemmer) vectors. Questions come from
eval/questions.jsonl (single questions) and eval/results/followup-current-*.json (follow-up turns with
the recorded real answers as history, refusals left out as the app does).

Variants:
  dense         what the app does today
  bm25          sparse keyword search alone
  hybrid_rrf    dense and BM25 candidates merged with Reciprocal Rank Fusion
  hybrid_gated  hybrid order, but a chunk is kept only if its dense cosine score passes the threshold
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.models import Base, Document
from app.repositories.vector_store import VectorStore
from app.services.authorization import allowed_document_ids
from app.services.chat import retrieval_query
from app.services.embeddings import get_embedder
from app.services.prompt import HistoryTurn
from app.services.sparse import get_sparse_encoder
from scripts.doc2dial_eval import RERANKER, load_reranker
from scripts.rag_eval import ROOT, _rate, load_questions, prepare_isolated_corpus

RESULTS_DIR = ROOT / "eval" / "results"
CANDIDATES = 20
VARIANTS = ("dense", "bm25", "hybrid_rrf", "hybrid_gated", "dense_rerank", "hybrid_rerank")


def _dense_of(point: models.ScoredPoint) -> list[float]:
    vector = point.vector
    if not isinstance(vector, dict) or not isinstance(vector.get("dense"), list):
        raise ValueError("dense vector missing")
    return cast(list[float], vector["dense"])


def _cases() -> list[dict[str, Any]]:
    """Tek sorular ve kayıtlı gerçek geçmişli takip turları; her biri beklenen belge veya ret bilgisiyle."""
    cases = [
        {"id": q.id, "kind": "single", "user": q.user_email, "query": q.question,
         "expected": q.expected_document, "should_abstain": q.should_abstain, "forbidden": q.unauthorized_document}
        for q in load_questions()
    ]
    emails = {json.loads(line)["id"]: json.loads(line)["user_email"]
              for line in (ROOT / "eval" / "conversations.jsonl").read_text(encoding="utf-8").splitlines() if line}
    followup = sorted(RESULTS_DIR.glob("followup-current-*.json"))[-1]
    turns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in json.loads(followup.read_text(encoding="utf-8"))["results"]:
        turns[row["scenario"]].append(row)
    for scenario, rows in turns.items():
        history: list[HistoryTurn] = []
        for row in rows:
            if row["turn"] > 1:
                cases.append({
                    "id": f"{scenario}-t{row['turn']}", "kind": row["category"], "user": emails[scenario],
                    "query": retrieval_query(row["question"], history), "expected": row["expected_document"],
                    "should_abstain": row["should_abstain"], "forbidden": None,
                })
            if not row["did_abstain"]:  # uygulama ret turlarını bağlama almaz
                history += [HistoryTurn("user", row["question"]), HistoryTurn("assistant", row["answer"])]
    return cases


def run(rerank_device: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    reranker = load_reranker(rerank_device) if rerank_device else None
    variants = VARIANTS if reranker else VARIANTS[:4]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    embedder = get_embedder()
    source = QdrantClient(":memory:")
    store = VectorStore(source, "demo", embedder.dimension, get_sparse_encoder())
    store.ensure_collection()
    bm25 = SparseTextEmbedding("Qdrant/bm25", cache_dir=settings.model_cache_dir, language="turkish")
    client = QdrantClient(":memory:")
    client.create_collection(
        "hybrid",
        vectors_config={"dense": models.VectorParams(size=embedder.dimension, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    Base.metadata.create_all(engine)
    rows = []
    with Session(engine) as db:
        users = prepare_isolated_corpus(db, store, embedder)
        filenames = {document.id: document.filename_original for document in db.scalars(select(Document))}
        points, _ = source.scroll("demo", limit=10_000, with_vectors=True, with_payload=True)
        sparse = list(bm25.embed([(point.payload or {})["text"] for point in points]))
        client.upsert("hybrid", [
            models.PointStruct(id=point.id, payload=point.payload, vector={
                "dense": point.vector["dense"],  # pyright: ignore[reportArgumentType, reportIndexIssue, reportOptionalSubscript, reportCallIssue]
                "bm25": models.SparseVector(indices=vector.indices.tolist(), values=vector.values.tolist()),
            })
            for point, vector in zip(points, sparse, strict=True)
        ])
        for case in _cases():
            allowed = list(allowed_document_ids(db, users[case["user"]]))
            acl = models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchAny(any=allowed))])
            dense = embedder.embed_query(case["query"])
            sparse_query = next(iter(bm25.query_embed(case["query"])))
            sparse_vector = models.SparseVector(indices=sparse_query.indices.tolist(), values=sparse_query.values.tolist())
            prefetch = [
                models.Prefetch(query=dense, using="dense", filter=acl, limit=CANDIDATES),
                models.Prefetch(query=sparse_vector, using="bm25", filter=acl, limit=CANDIDATES),
            ]
            requests: dict[str, dict[str, Any]] = {
                "dense": {"query": dense, "using": "dense", "limit": settings.retrieval_top_k},
                "bm25": {"query": sparse_vector, "using": "bm25", "limit": settings.retrieval_top_k},
                "hybrid_rrf": {"prefetch": prefetch, "query": models.FusionQuery(fusion=models.Fusion.RRF),
                               "limit": settings.retrieval_top_k},
                "hybrid_gated": {"prefetch": prefetch, "query": models.FusionQuery(fusion=models.Fusion.RRF),
                                 "limit": CANDIDATES, "with_vectors": ["dense"]},
            }
            if reranker is not None:
                requests["dense_rerank"] = {"query": dense, "using": "dense", "limit": CANDIDATES}
                requests["hybrid_rerank"] = {"prefetch": prefetch, "query": models.FusionQuery(fusion=models.Fusion.RRF),
                                             "limit": CANDIDATES}
            row: dict[str, Any] = {"id": case["id"], "kind": case["kind"]}
            for name, request in requests.items():
                result = client.query_points("hybrid", query_filter=acl, with_payload=True, **request).points
                if name == "hybrid_gated":
                    # Vektörler normalize: iç çarpım = kosinüs. Eşik her parçanın dense skoruna uygulanır.
                    scored = [(point, sum(a * b for a, b in zip(dense, _dense_of(point), strict=True)))
                              for point in result]
                    result = [point for point, cosine in scored if cosine >= settings.retrieval_min_score]
                    result = result[: settings.retrieval_top_k]
                elif name.endswith("_rerank") and reranker is not None and result:
                    scores = list(reranker.rerank(case["query"], [(point.payload or {})["text"] for point in result]))
                    result = [point for _, point in sorted(zip(scores, result, strict=True), key=lambda pair: -pair[0])]
                    result = result[: settings.retrieval_top_k]
                files = [filenames[(point.payload or {})["document_id"]] for point in result]
                row[name] = {
                    "first": bool(files) and files[0] == case["expected"] if case["expected"] else None,
                    "in_top5": case["expected"] in files if case["expected"] else None,
                    "forbidden_seen": case["forbidden"] in files if case["forbidden"] else False,
                    "returned": len(files),
                }
            if case["should_abstain"]:
                # Ret beklenen soruda dense ve eşikli hibrit için "ilk katman reddetti mi": hiç parça geçmedi mi?
                top_dense = client.query_points("hybrid", query=dense, using="dense", query_filter=acl, limit=1).points
                row["dense_gate_rejects"] = not top_dense or top_dense[0].score < settings.retrieval_min_score
                row["gated_rejects"] = row["hybrid_gated"]["returned"] == 0
            rows.append(row)

    answerable = [row for row in rows if row["dense"]["first"] is not None]
    refusals = [row for row in rows if "dense_gate_rejects" in row]
    metrics: dict[str, Any] = {}
    for name in variants:
        metrics[name] = {
            "first": _rate([row[name]["first"] for row in answerable]),
            "in_top5": _rate([row[name]["in_top5"] for row in answerable]),
            "first_by_kind": {
                kind: _rate([row[name]["first"] for row in answerable if row["kind"] == kind])
                for kind in sorted({row["kind"] for row in answerable})
            },
            "forbidden_document_seen": sum(row[name]["forbidden_seen"] for row in rows),
        }
    metrics["first_layer_refusal"] = {
        "dense_threshold": _rate([row["dense_gate_rejects"] for row in refusals]),
        "hybrid_gated": _rate([row["gated_rejects"] for row in refusals]),
    }
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "corpus": "data/demo_docs (13 synthetic Turkish/English documents)",
        "embedding_model": settings.embedding_model, "sparse_model": "Qdrant/bm25 (turkish stemmer, IDF)",
        "retrieval_min_score": settings.retrieval_min_score, "candidates": CANDIDATES,
        "reranker": f"{RERANKER} ({rerank_device})" if rerank_device else None,
        "cases": len(rows), "answerable": len(answerable), "refusal_cases": len(refusals),
        "metrics": metrics, "results": rows,
    }
    suffix = f"-rerank-{rerank_device}" if rerank_device else ""
    output = RESULTS_DIR / f"hybrid-demo{suffix}-{datetime.now(UTC).date().isoformat()}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **{k: v for k, v in report.items() if k != "results"}}, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rerank-device", choices=["cpu", "gpu"], help="Yeniden sıralama varyantlarını da ölç")
    run(parser.parse_args().rerank_device)
