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
