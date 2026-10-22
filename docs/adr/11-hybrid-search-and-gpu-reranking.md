# 11 — Hybrid search always on, GPU re-ranking behind `GPU_ENABLED`

**Status:** Accepted  
**Date:** 2026-10-22

## Context

ADR-10 measured that the right document is usually among the top candidates but not always first, and that hybrid search plus cross-encoder re-ranking was the best configuration: on 908 doc2dial follow-up turns the right document came first in 78.6% of turns instead of 66.5%, and the answering span reached the top five in 75.5% instead of 62.8%. On the Turkish demo set the combination reached 33/34 and fixed the topic-switch miss. Re-ranking takes 0.34 s per query on an RTX 4050 but about 14 s on CPU. The app must keep running on machines without a GPU, and a misconfigured GPU must not silently fall back to a slow or different mode.

## Options considered

1. Keep dense retrieval only.
2. Hybrid search and re-ranking only together, both behind one GPU switch.
3. Hybrid search always on; re-ranking only when `GPU_ENABLED=true`.

## Decision

Option 3, as the project owner chose after the measurements.

**Hybrid search.** The Qdrant collection `knowledge_chunks_v2` stores two named vectors per chunk: `dense` (multilingual-e5-large) and `bm25` (fastembed `Qdrant/bm25`, Turkish stemmer). Chunk vectors carry term frequencies; Qdrant applies IDF from collection statistics (`Modifier.IDF`). A query runs two candidate searches of at least 20 chunks each and merges them with Reciprocal Rank Fusion. The SQLite allowlist is applied to both candidate searches and to the fused query, and an empty allowlist still means Qdrant is never called. RRF scores are rank based and cannot be compared with the measured 0.80 threshold, so each hit's score is the dense cosine similarity computed from its stored vector; the threshold keeps working exactly as before, only the order comes from fusion.

**Re-ranking.** With `GPU_ENABLED=true`, `/chat` retrieves `RERANK_CANDIDATES` (20) chunks, drops those below the threshold, re-orders the rest with `BAAI/bge-reranker-v2-m3` (Apache-2.0, fp16 ONNX on CUDA) and keeps the top five. Chunks below the threshold never reach the re-ranker or the LLM. With `GPU_ENABLED=false` (the default) no re-ranker is loaded. If the switch is on but CUDA is not available, `/chat` returns 503 with setup instructions, the same way a missing LLM key is reported; canned replies keep working.

**GPU environment.** `onnxruntime-gpu` provides the same Python module as the CPU `onnxruntime` that fastembed depends on, so they cannot share an environment. `scripts/setup_gpu_env.ps1` builds `.venv-gpu` from `uv.lock`, swaps in `onnxruntime-gpu` of the locked version with the CUDA and cuDNN pip packages, and checks the CUDA provider. The API is then started with that interpreter. No CUDA Toolkit install is needed; the NVIDIA driver must report CUDA 13 or newer.

**Migration.** `scripts/reindex_hybrid.py` copies the dense vectors and payloads of the old `knowledge_chunks_v1` collection into v2 and computes only the BM25 vectors, so the embedding model does not run again. The old collection stays for rollback. Opening a v1 collection with the new code fails with a message that names the script.

## Consequences

Every query now runs two candidate searches; on the demo corpus this adds milliseconds. Hybrid search alone lost one Turkish topic-switch question that re-ranking recovers, so machines without a GPU trade that case for better keyword matching (form codes, port numbers, product names), which doc2dial showed to be a large gain. BM25 uses one stemmer for the whole corpus; English chunks are stemmed with Turkish rules, which still matches exact terms. The GPU path is a local-machine option; a hosted deployment without a GPU keeps re-ranking off.

## Evidence

Tests: the ACL filter on both candidate searches (a document that matches only by a rare keyword is not returned outside the allowlist), exact keyword retrieval that the dense query alone misses, dense cosine scores instead of fusion scores, rejection of the old schema with a migration hint, reindexing with preserved vectors and idempotent reruns, a re-ranker that can promote a chunk from the wider pool, chunks below the threshold never reaching the re-ranker, no re-ranker when the switch is off, and a 503 when it is on without CUDA. Mutation checks removing either ACL filter, the BM25 search, the cosine score, the threshold-before-rerank order or the wider candidate pool each made a test fail. Live E2 runs with `openai/gpt-oss-120b` (22 questions, real models) showed no regression in either mode: Recall@5 16/16, expected answer facts 16/16, abstention 22/22, citation correctness 22/22 and zero ACL leaks, the same as dense retrieval. Retrieval took 61 ms on average with dense only, 90 ms with hybrid search on CPU, and 419 ms (262 ms median, first-query model warm-up included) with hybrid search plus GPU re-ranking. Results: `eval/results/hybrid-llm-2026-10-22.json`, `eval/results/hybrid-rerank-gpu-llm-2026-10-22.json`; the doc2dial and demo-set comparisons are in ADR-10.
