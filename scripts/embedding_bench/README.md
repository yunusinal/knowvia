# Embedding benchmark

A small, reproducible benchmark that compares local embedding models on synthetic company documents. It was used to choose the embedding model; see [ADR-05](../../docs/adr/05-embedding-model.md) for the results and the decision.

## What it measures

- **Retrieval quality**
  - Hit@1 and Hit@3: is the expected passage ranked first, or in the top three?
  - MRR (mean reciprocal rank)
  - Results per question type: paraphrase, keyword match, similar-passage and outdated-version traps, cross-language.
- **"No answer" separation:** top similarity scores for questions the documents cannot answer, compared with scores of correct answers.
- **Cost**
  - Disk size of the model
  - Process RAM
  - Load time
  - Time per passage and per query
  - Time for a realistic 350-token chunk

## Files

| File | Purpose |
|---|---|
| `bench.py` | Runs one model on one corpus and writes `results/<corpus>/<model>.json` |
| `long_chunk.py` | Times a ~350-token chunk |
| `analyze.py` | Hit@1 per question type, bootstrap confidence intervals, threshold analysis |
| `corpus_small.py` | 21 passages, 21 answerable + 5 unanswerable questions |
| `corpus_large.py` | 55 passages, 91 answerable + 15 unanswerable questions |
| `results/` | Raw results from the run recorded in ADR-05 |

## Models

| Name | Model |
|---|---|
| `e5-small` | `intfloat/multilingual-e5-small` |
| `e5-base` | `intfloat/multilingual-e5-base` |
| `e5-large` | `intfloat/multilingual-e5-large` |
| `qwen3-0.6b` | `Qwen/Qwen3-Embedding-0.6B` |

## Running (Windows PowerShell, from the repo root)

```powershell
# Install the project plus the benchmark-only dependency group (psutil)
uv sync --group bench

# One model on the large corpus (the first run downloads the model)
uv run --group bench python -m scripts.embedding_bench.bench e5-large corpus_large

# All models on both corpora
foreach ($m in "e5-small", "e5-base", "e5-large", "qwen3-0.6b") {
    foreach ($c in "corpus_small", "corpus_large") {
        uv run --group bench python -m scripts.embedding_bench.bench $m $c
    }
}

# Speed on a realistic 350-token chunk
uv run --group bench python -m scripts.embedding_bench.long_chunk e5-large

# Compare the results
uv run python -m scripts.embedding_bench.analyze corpus_large
```

Models are downloaded to `data/runtime/models/`, which is gitignored. Downloading all four models takes about 6.3 GB.

If Turkish characters look garbled in the terminal, set `$env:PYTHONIOENCODING = "utf-8"` first. The result files themselves are always UTF-8.
