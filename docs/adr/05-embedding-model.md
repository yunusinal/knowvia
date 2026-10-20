# ADR-05: Embedding model and runtime

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

Knowvia answers questions over company documents. Retrieval works by turning each document chunk and each question into a vector with an embedding model and returning the chunks whose vectors are closest to the question. If the right chunk is not retrieved, the LLM cannot answer correctly, so the embedding model largely determines answer quality.

Constraints:

- **Local and key-free.** The model runs on the developer's laptop (CPU only). Tests must run without any API key, and document text should not be sent to a third party just to be indexed.
- **Turkish first, English second.** The demo documents and questions are mostly Turkish, with some English documents and cross-language questions.
- **Lightweight install.** The project is a local demo that others should be able to clone and run.
- **Package cut-off.** `pyproject.toml` excludes package versions published after 2026-10-05.

Two choices are separate and were made separately:

1. **Runtime library:** the code that downloads the model, tokenizes text and runs the network.
2. **Model:** the trained weights. The same model gives the same vectors in any runtime, so this choice decides retrieval quality.

## Options considered

### Runtime

| Option | Inference engine | Notes |
|---|---|---|
| `sentence-transformers` 6.1.0 | PyTorch | De facto standard. Pulls in `torch`, `transformers`, `scipy`, `scikit-learn`. PyTorch also supports training, which this project does not need. |
| **`fastembed` 0.8.1** | ONNX Runtime 1.30.0 | Inference only. The whole benchmark environment was 138 MB. Supports custom models from Hugging Face (`add_custom_model`) and ships Qwen3-Embedding. Maintained by Qdrant, our vector database. |
| Hosted embedding API (e.g. OpenAI `text-embedding-3-small`) | Remote | No local install, but it needs a key, costs money, sends every chunk to the provider and makes tests key-dependent. |

### Model

| Model | Params | Dim | Max tokens | License |
|---|---|---|---|---|
| `intfloat/multilingual-e5-small` | 118 M | 384 | 512 | MIT |
| `intfloat/multilingual-e5-base` | 278 M | 768 | 512 | MIT |
| `intfloat/multilingual-e5-large` | 560 M | 1024 | 512 | MIT |
| `Qwen/Qwen3-Embedding-0.6B` | 596 M | 1024 | 32 768 | Apache-2.0 |

`BAAI/bge-m3` (~2.3 GB of weights) was not benchmarked because of its size. `google/embeddinggemma-300m` was not benchmarked because it is gated: downloading it requires a Hugging Face account and accepting a licence, which would complicate setup for anyone running the demo.

## Benchmark

Code, data and raw results: [`scripts/embedding_bench/`](../../scripts/embedding_bench/).

All models were run through fastembed with each model's recommended prefixes (`query: ` / `passage: ` for E5, the default instruction for Qwen3). Vectors were L2-normalized and ranked by cosine similarity.

**Hardware:** AMD Ryzen 5 7535HS (6 cores / 12 threads), 23 GB RAM, Windows 11, CPU only.

**Data:** synthetic company documents (HR, IT, Finance) written for this test.

| | Small set | Large set |
|---|---|---|
| Passages | 21 | 55 |
| Answerable questions | 21 | 91 |
| Unanswerable questions | 5 | 15 |

The large set has these question types:

| Type | Count |
|---|---|
| Paraphrase: Turkish question, no shared keywords with the passage | 49 |
| Direct keyword match | 13 |
| Similar-passage trap (e.g. domestic vs. abroad meal limit) | 7 |
| Outdated-version trap (2024 archived vs. 2026 policy) | 4 |
| English question → Turkish passage | 7 |
| Turkish question → English passage | 7 |
| English question → English passage | 4 |

### Retrieval quality

| Hit@1 (correct chunk ranked first) | Small set | Large set |
|---|---|---|
| e5-small | 67% | 67% |
| e5-base | 71% | 79% |
| **e5-large** | 86% | **90%** |
| Qwen3-0.6B | **90%** | 80% |

On the large set, e5-large reaches 93% Hit@3 and 0.93 MRR. Qwen3 reaches 95% Hit@3 and 0.88 MRR.

### By question type (large set)

| Type | small | base | large | qwen3 |
|---|---|---|---|---|
| Paraphrase (TR → TR) | 34/49 | 41/49 | **48/49** | 38/49 |
| Direct keyword | 13/13 | 13/13 | 13/13 | 13/13 |
| Similar-passage trap | 5/7 | 6/7 | **7/7** | 6/7 |
| Outdated-version trap | 1/4 | 2/4 | 3/4 | 3/4 |
| EN question → TR passage | 4/7 | 5/7 | 5/7 | **6/7** |
| TR question → EN passage | 0/7 | 1/7 | 2/7 | **3/7** |
| EN → EN | 4/4 | 4/4 | 4/4 | 4/4 |

### Is the difference real?

Paired bootstrap of the Hit@1 difference, resampling the 91 questions 10 000 times, 95% interval:

| Comparison | Difference | 95% CI | Reading |
|---|---|---|---|
| e5-large − Qwen3 | +9.9 pts | [+1.1, +18.7] | significant |
| e5-large − e5-base | +11.0 pts | [+5.5, +17.6] | significant |
| e5-base − e5-small | +12.1 pts | [+5.5, +18.7] | significant |
| Qwen3 − e5-base | +1.1 pts | [−6.6, +8.8] | could be chance |

The small set had shown Qwen3 slightly ahead. With four times more questions the order reversed, and the gap became significant. Small evaluation sets are noisy.

### Cost

| | e5-small | e5-base | e5-large | Qwen3-0.6B |
|---|---|---|---|---|
| Disk | 487 MB | 1.1 GB | 2.3 GB | 2.4 GB |
| Peak process RAM | ~1.0 GB | ~2.0 GB | ~2.0 GB | ~3.0 GB |
| One 350-token chunk | 72 ms | 223 ms | 756–775 ms | 1 168 ms |
| Indexing 100 chunks | ~7 s | ~22 s | ~78 s | ~117 s |
| One query | 6 ms | 16 ms | 52 ms | 137 ms |
| Load from cache | 1.5 s | 2.9 s | 2.8 s | 3.7 s |
| Avg tokens per passage | 58–60 | 58–60 | 58–60 | 77 |

Query latency is negligible next to the LLM call for every model. The real costs are the one-time model download and the indexing time. Qwen3's tokenizer splits the same Turkish text into about 30% more tokens than E5's.

## Decision

1. **Runtime:** `fastembed` (ONNX Runtime). It gives the same vectors as the PyTorch stack for a fraction of the install size.
2. **Model:** `intfloat/multilingual-e5-large`.
   - It is loaded from the model's official ONNX file (`onnx/model.onnx` + `onnx/model.onnx_data`) via `add_custom_model`, with mean pooling and L2 normalization.
   - fastembed's built-in `intfloat/multilingual-e5-large` entry is **not** used. It points to a different ONNX export and does not normalize, so it is not the configuration that was measured.
3. **Prefixes are added explicitly** by our adapter: `passage: ` for chunks, `query: ` for questions. fastembed does not add them, and forgetting them degrades quality without any error.
4. **Chunk length is measured in tokens with the model's own tokenizer**, including the `passage: ` prefix.
   - Target: ~350 tokens with ~50 tokens of overlap.
   - A test asserts that no chunk exceeds the model's 512-token limit. Beyond that limit, text is silently truncated and never becomes searchable.
5. **The model name is configuration, not code.** Switching models means changing the setting and re-indexing every document, because vectors from different models are not comparable and the dimension changes.

## Consequences

**Gains**

- The best retrieval quality on the dominant use case (Turkish question, Turkish document).
- No PyTorch dependency.
- No API key and no document text leaving the machine for indexing.

**Accepted costs**

- A 2.3 GB first-time download.
- ~2 GB RAM while the backend runs.
- Indexing is roughly 10× slower than with e5-small. That is still about a minute for the demo corpus.
- Unit tests do not load the real model: they use a deterministic fake embedding, so test speed is unaffected.

**Findings that affect other parts of the design**

- **A similarity threshold cannot detect "no answer" on its own.** With e5-large, rejecting every unanswerable question would also reject 29% of correct answers. Accepting a 10% loss of correct answers catches 93% of unanswerable questions. The threshold (`RETRIEVAL_MIN_SCORE`) is therefore only a coarse first filter. The LLM's `INSUFFICIENT_CONTEXT` signal remains required.
- **Thresholds are model-specific.** E5 compresses scores into a narrow band (unrelated text still scores ~0.78). Qwen3 scores live around 0.3–0.8. If the model changes, the threshold must be re-measured.
- **Embeddings cannot tell which policy version is current.** e5-large still ranked the archived 2024 policy first for one question. Outdated documents must be excluded by status metadata, not left to similarity.
- **Cross-language retrieval (TR ↔ EN) is the weakest area for every model.** At most 3 of 7 Turkish questions found the English passage. Keeping demo documents in the same language as the expected questions avoids the issue.

**Revisit when**

- the real demo documents exist (Milestone E evaluation);
- the corpus or the hardware changes significantly;
- a Turkish instruction for Qwen3 is tested. Only the default English instruction was used, so Qwen3 may be under-rated here.

## Limitations of this benchmark

- The documents and questions were written for this benchmark (with AI assistance), not collected from real users. Different phrasing could change the results.
- 91 questions is still small: one question is worth about 1 point of Hit@1.
- Benchmark passages are short (~60 tokens). Speed was also measured on 350-token chunks, but quality was not.
- RAM figures are process measurements on one machine, not guarantees.

## Sources

- Model cards and file listings on Hugging Face: [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small), [multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base), [multilingual-e5-large](https://huggingface.co/intfloat/multilingual-e5-large), [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [qdrant/fastembed](https://github.com/qdrant/fastembed) v0.8.1 source: custom model registration and the built-in e5-large / Qwen3 entries
- Dependency trees resolved with `uv pip compile` for Windows / Python 3.12 under the 2026-10-05 cut-off
