"""Bir embedding modelini sentetik veri setinde ölçer: arama kalitesi, RAM, hız, disk.

Çalıştırma (repo kökünden):
    uv run --group bench python -m scripts.embedding_bench.bench e5-large corpus_large

Sonuçlar scripts/embedding_bench/results/<corpus>/<model>.json dosyasına yazılır.
"""

import importlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import psutil
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

BENCH_DIR = Path(__file__).resolve().parent
# Model dosyaları (birkaç GB) git dışındaki çalışma zamanı klasöründe tutulur.
CACHE_DIR = BENCH_DIR.parents[1] / "data" / "runtime" / "models"

QWEN_INSTRUCT = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
)


@dataclass(frozen=True)
class ModelSpec:
    fastembed_name: str
    hf_repo: str
    query_prefix: str
    passage_prefix: str
    # Yalnızca fastembed'in hazır listesinde olmayan modeller için: add_custom_model ile kaydedilir.
    custom_dim: int | None = None
    custom_extra_files: tuple[str, ...] = ()


MODELS: dict[str, ModelSpec] = {
    "e5-small": ModelSpec(
        "intfloat/multilingual-e5-small", "intfloat/multilingual-e5-small",
        "query: ", "passage: ", custom_dim=384,
    ),
    "e5-base": ModelSpec(
        "intfloat/multilingual-e5-base", "intfloat/multilingual-e5-base",
        "query: ", "passage: ", custom_dim=768,
    ),
    # fastembed'in hazır e5-large kaydı Qdrant'ın kendi ONNX dönüşümünü normalize etmeden kullanır;
    # bunun yerine modelin resmi ONNX dosyası ayrı bir adla kaydedilir.
    "e5-large": ModelSpec(
        "intfloat/multilingual-e5-large-custom", "intfloat/multilingual-e5-large",
        "query: ", "passage: ", custom_dim=1024, custom_extra_files=("onnx/model.onnx_data",),
    ),
    "qwen3-0.6b": ModelSpec(
        "Qwen/Qwen3-Embedding-0.6B", "Qdrant/Qwen3-Embedding-0.6B-onnx",
        QWEN_INSTRUCT, "",
    ),
}


def load_model(name: str) -> tuple[TextEmbedding, ModelSpec]:
    spec = MODELS[name]
    if spec.custom_dim is not None:
        TextEmbedding.add_custom_model(
            model=spec.fastembed_name,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=spec.hf_repo),
            dim=spec.custom_dim,
            model_file="onnx/model.onnx",
            additional_files=list(spec.custom_extra_files) or None,
        )
    return TextEmbedding(model_name=spec.fastembed_name, cache_dir=str(CACHE_DIR)), spec


def count_tokens(model: TextEmbedding, texts: list[str]) -> list[int]:
    """Token'ları modelin kendi tokenizer'ıyla sayar (padding kapalı; yoksa her metin en uzun metin kadar sayılır)."""
    tokenizer = model.model.tokenizer  # pyright: ignore[reportAttributeAccessIssue]
    tokenizer.no_padding()
    return [len(enc.ids) for enc in tokenizer.encode_batch(texts)]


def model_disk_mb(spec: ModelSpec) -> float:
    # Hugging Face önbelleğinde gerçek dosyalar blobs/ altındadır; snapshots/ yalnızca bağlantıdır.
    folder = CACHE_DIR / ("models--" + spec.hf_repo.replace("/", "--"))
    blobs = folder / "blobs"
    root = blobs if blobs.exists() else folder
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) / 1e6


def main(name: str, corpus_name: str) -> None:
    corpus = importlib.import_module(f"scripts.embedding_bench.{corpus_name}")
    passages: dict[str, str] = corpus.PASSAGES
    questions: list[tuple[str, str, str]] = corpus.QUESTIONS
    no_answer_questions: list[str] = corpus.NO_ANSWER

    proc = psutil.Process()
    rss_before = proc.memory_info().rss / 1e6
    start = time.perf_counter()
    model, spec = load_model(name)
    list(model.embed(["ısınma"]))  # ilk ve yavaş çağrı ölçüme girmesin
    load_s = time.perf_counter() - start
    rss_loaded = proc.memory_info().rss / 1e6

    ids = list(passages)
    texts = [spec.passage_prefix + passages[pid] for pid in ids]
    start = time.perf_counter()
    doc_vecs = np.array(list(model.embed(texts)))
    index_s = time.perf_counter() - start

    query_times: list[float] = []

    def search(question: str) -> list[tuple[str, float]]:
        t = time.perf_counter()
        q_vec = np.array(list(model.embed([spec.query_prefix + question])))[0]
        query_times.append(time.perf_counter() - t)
        scores = doc_vecs @ q_vec  # vektörler normalize: iç çarpım = cosine benzerliği
        return [(ids[k], float(scores[k])) for k in np.argsort(-scores)]

    rows = []
    for question, expected, kind in questions:
        ranked = search(question)
        rank = [pid for pid, _ in ranked].index(expected) + 1
        rows.append({
            "question": question,
            "kind": kind,
            "expected": expected,
            "rank": rank,
            "top1": ranked[0][0],
            "top1_score": round(ranked[0][1], 4),
            "expected_score": round(dict(ranked)[expected], 4),
        })

    no_answer = []
    for question in no_answer_questions:
        top_id, top_score = search(question)[0]
        no_answer.append({"question": question, "top1": top_id, "top1_score": round(top_score, 4)})

    token_counts = count_tokens(model, texts)
    ranks = [r["rank"] for r in rows]
    hit_scores = [r["expected_score"] for r in rows if r["rank"] == 1]
    result = {
        "model": name,
        "corpus": corpus_name,
        "dim": int(doc_vecs.shape[1]),
        "hit@1": round(sum(r == 1 for r in ranks) / len(ranks), 4),
        "hit@3": round(sum(r <= 3 for r in ranks) / len(ranks), 4),
        "mrr": round(sum(1 / r for r in ranks) / len(ranks), 3),
        "min_correct_top1_score": round(min(hit_scores), 4) if hit_scores else None,
        "max_no_answer_score": round(max(n["top1_score"] for n in no_answer), 4),
        "disk_mb": round(model_disk_mb(spec)),
        "ram_model_mb": round(rss_loaded - rss_before),
        # peak_wset (en yüksek bellek kullanımı) yalnızca Windows'ta var; diğer sistemlerde anlık RSS kullanılır.
        "ram_peak_process_mb": round(getattr(proc.memory_info(), "peak_wset", proc.memory_info().rss) / 1e6),
        "load_s": round(load_s, 1),
        "index_ms_per_passage": round(index_s / len(texts) * 1000, 1),
        "query_ms_avg": round(sum(query_times) / len(query_times) * 1000, 1),
        "avg_tokens_per_passage": round(sum(token_counts) / len(token_counts), 1),
        "max_tokens_per_passage": max(token_counts),
        "avg_chars_per_passage": round(sum(map(len, texts)) / len(texts), 1),
        "questions": rows,
        "no_answer": no_answer,
    }

    out_dir = BENCH_DIR / "results" / corpus_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k not in ("questions", "no_answer")}
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "corpus_large")
