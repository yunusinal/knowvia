# 10 — Re-ranking: measured, deferred for latency

**Status:** Accepted  
**Date:** 2026-10-22

## Context

On doc2dial follow-up turns (ADR-08) the right document was usually among the top five chunks but not first: 67.0% first, 85.0% in the top five. A stress test with unrelated earlier exchanges showed the same pattern. A cross-encoder re-ranker scores each (query, chunk) pair jointly and is the usual fix for ordering errors (master plan F2). The product answers Turkish and English, and its claims should not depend on a model whose license forbids commercial use.

## Options considered

1. `jinaai/jina-reranker-v2-base-multilingual`: multilingual and supported by fastembed, but CC BY-NC 4.0.
2. `BAAI/bge-reranker-base`: MIT, but English and Chinese only.
3. `BAAI/bge-reranker-v2-m3` (Apache-2.0, multilingual), loaded in fastembed as a custom model from the `onnx-community` int8 ONNX export.

## Decision

Option 3 was measured: the current query retrieves 20 candidates, the re-ranker orders them, and the top five are scored. On a fixed 300-turn sample (seed 7) of the doc2dial DMV validation set:

| | First | Top 5 | Answer span in top 5 |
|---|---|---|---|
| Current retrieval | 64.3% | 86.0% | 64.0% |
| + re-ranking | 76.3% | 90.3% | 70.0% |

The right document was among the 20 candidates in 94.3% of turns. Re-ranking took 14.3 s per query on average (max 18.5 s) on the development CPU, against roughly 2–3 s for a whole answer today. Re-ranking is therefore **not** added to the app now.

## Consequences

The gain is real and recorded, so the option can be revisited when one of these holds: a GPU is available, a smaller multilingual Apache/MIT re-ranker appears, or fewer candidates (5–10) are measured to keep latency acceptable. The measurement code stays in `scripts/doc2dial_eval.py --rerank-sample`. Until then, answers rely on the top five from dense retrieval, which contain the right document about 85–90% of the time on doc2dial.

## Evidence

`eval/results/doc2dial-dmv-plain-rerank-2026-10-22.json` (IDs and metrics only). The model is downloaded into the gitignored model cache on first use (about 0.57 GB).

## Update (2026-10-22): GPU and hybrid search

On an RTX 4050 Laptop GPU (driver 621, CUDA 13) with `onnxruntime-gpu` 1.30 and the fp16 model, re-ranking the same 300 turns took **0.34 s** per query on average (1.0 s at most, the first warm-up call), with the same quality (first 75.3%, top 5 90.0%, answer span 71.0%). The CUDA and cuDNN libraries come from pip packages loaded with `onnxruntime.preload_dlls()`; no CUDA Toolkit install is needed, but `onnxruntime-gpu` cannot share an environment with `onnxruntime`, so the GPU run used a separate virtual environment under `data/runtime/`.

Hybrid search (dense plus `Qdrant/bm25` sparse vectors with an IDF modifier, merged with Reciprocal Rank Fusion over 20 candidates each, with the ACL filter on both prefetches) was measured on all 908 doc2dial turns:

| | First | Top 5 | Answer span in top 5 |
|---|---|---|---|
| Dense (today) | 66.5% | 85.1% | 62.8% |
| BM25 only | 72.4% | 90.5% | 60.4% |
| Hybrid (RRF) | 71.7% | 92.8% | 67.4% |
| Dense + re-ranking | 76.3% | 90.2% | 72.0% |
| Hybrid + re-ranking | 78.6% | 93.7% | 75.5% |

On the Turkish demo set (34 answerable single and follow-up questions, Turkish stemmer) dense was already at 32/34; hybrid alone dropped to 31/34 (one topic-switch question, because BM25 matches words of the previous topic carried in the query), while both re-ranked variants reached 33/34 and solved every topic switch. No variant surfaced a document outside the user's ACL. Applying the 0.80 threshold to each chunk's dense score inside the hybrid order kept the first refusal layer unchanged (5/11 refusal cases rejected before the LLM, as with dense).

Hybrid search plus re-ranking is therefore the best measured configuration; re-ranking is practical only where a GPU is available. Wiring them into the app is a separate decision. Results: `eval/results/doc2dial-dmv-plain-rerank-gpu-2026-10-22.json`, `doc2dial-dmv-plain-hybrid-2026-10-22.json`, `doc2dial-dmv-plain-hybrid-rerank-gpu-2026-10-22.json`, `hybrid-demo-2026-10-22.json`, `hybrid-demo-rerank-gpu-2026-10-22.json`.
