# ADR-07: Paragraph-preserving chunking and a measured retrieval threshold

- **Status:** Accepted. Supersedes the chunk merge strategy of [ADR-06](06-own-text-splitter.md); ADR-06's decision to use our own splitter still stands.
- **Date:** 2026-10-21

## Context

Two things had to be decided before the chat endpoint:

1. **`RETRIEVAL_MIN_SCORE`.** If the best search result scores below this threshold, the LLM is not called and the answer is "no evidence". The master plan requires this value to be measured on demo questions, not guessed.
2. **How chunks are formed.** The threshold depends on the chunking method, so both were measured together.

ADR-06 split each page into pieces and **greedily merged** consecutive pieces up to ~350 tokens. On the 13 demo documents this packed unrelated paragraphs into one chunk: one employee-handbook chunk held working hours, dress code and gift rules together. The vector of such a chunk drifts toward the average of its topics and matches none of them well.

## Measurement

Script: [`scripts/embedding_bench/threshold.py`](../../scripts/embedding_bench/threshold.py). Raw results: [`scripts/embedding_bench/results/threshold/`](../../scripts/embedding_bench/results/threshold/).

**Setup**

- A fresh, temporary SQLite and Qdrant are created; the project database is not touched.
- The 13 demo documents are indexed through the real upload flow with `multilingual-e5-large`.
- The benchmark questions (91 answerable, 15 unanswerable) are asked through the real access-filtered retrieval (`top_k = 5`) as each of the four demo users.

**The 424 observations fall into three groups**

| Group | Count | Meaning |
|---|---|---|
| Should answer | 328 | The answer is in a document the user can access |
| Should refuse: unauthorized | 36 | The answer exists, but only in a document the user cannot access |
| Should refuse: no evidence | 60 | No document contains the answer |

Unauthorized documents never appear in results; the access filters remove them. For the second group, the question is whether the user's *other* accessible chunks score high enough to reach the LLM.

### Chunking methods

| Method | Chunks | Expected document ranked first | Expected document in top 5 (LLM context) |
|---|---|---|---|
| A. Greedy merge up to 350 tokens (ADR-06) | 16 | 68.3% | 93.9% |
| B. Greedy merge up to 120 tokens | 41 | 84.1% | 95.1% |
| B'. Greedy merge up to 200 tokens | 25 | 76.8% | 94.2% |
| **C. Paragraph-preserving, max 350, min 50** | 54 | **87.2%** | **96.0%** |
| D. C + document title prepended to each chunk | 54 | 84.1% | 95.7% |

Method D was measured with a one-off script that is not part of the repository.

**What the table shows**

- **Size was not the problem; mixing paragraphs was.** C allows chunks up to 350 tokens and still beats the 120-token fixed budget.
- **Very small fixed chunks would also hurt documents with long paragraphs.** Published benchmarks report quality dropping with over-fragmented chunks.
- **The document title did not help here.** Each demo paragraph already starts with its own title (e.g. "Çalışan El Kitabı — Kıyafet…"), and a shared prefix made chunks of the same document more alike. Contextual headers remain a candidate for real documents whose paragraphs lack titles.

### Threshold (method C)

| Threshold | Should answer: passes | Unauthorized: passes | No evidence: passes |
|---|---|---|---|
| 0.78 | 98.8% | 94.4% | 93.3% |
| 0.79 | 97.6% | 86.1% | 58.3% |
| **0.80** | **97.3%** | **66.7%** | **40.0%** |
| 0.81 | 90.2% | 44.4% | 26.7% |

The score ranges of the three groups overlap:

| Group | Lowest | Median | Highest |
|---|---|---|---|
| Should answer | 0.779 | 0.846 | 0.916 |
| Unauthorized | 0.774 | 0.806 | 0.839 |
| No evidence | 0.773 | 0.796 | 0.838 |

## Decision

1. **Chunking (`app/services/chunking.py`).**
   - Every paragraph (separated by a blank line) is its own chunk. Different paragraphs are never merged.
   - A paragraph under `min_tokens = 50` (a heading, a one-line note) joins the next paragraph. At the end of a page it joins the previous one.
   - A paragraph over the 350-token budget is split inside, using the ADR-06 separators (sentence end → line → clause → word → character) with whole-piece overlap of up to 50 tokens.
   - Overlap is never carried across a paragraph boundary.
   - Chunks still never span pages.
2. **Threshold:** `RETRIEVAL_MIN_SCORE = 0.80` (configurable). This trades about 3% of answerable questions for rejecting 60% of unanswerable ones and a third of unauthorized-answer questions before any LLM call.
3. **Top k:** `RETRIEVAL_TOP_K = 5` (configurable).
4. **The threshold is only the first of two abstention layers.** The LLM's `INSUFFICIENT_CONTEXT` signal remains required, because 40% of unanswerable questions still pass the threshold.

## Consequences

**Gains**

- 87% of answerable questions now rank the right document first, up from 68%.
- Context sent to the LLM is focused on one topic per chunk, and citations point at the paragraph that holds the answer.
- About 60% of questions without evidence never reach the LLM.

**Accepted costs**

- About 3% of answerable questions are refused at the threshold.
- More, smaller chunks: 54 instead of 16 for the demo corpus. Negligible at this scale.
- Broad questions ("summarise the remote work policy") receive at most 5 paragraphs; `RETRIEVAL_TOP_K` can be raised if this proves too little.

**Limitations and when to revisit**

- PDF text often has no blank lines between paragraphs (the Turkish PDF fixture has none). Such a page is one block, and C falls back to ADR-06 behaviour: in-paragraph splitting up to 350 tokens. Results are no worse than A, but the improvement does not apply. Detecting paragraphs from PDF layout is a possible later improvement.
- The demo paragraphs are short (~60 tokens) and self-titled. Real documents with long or untitled paragraphs may favour different settings or contextual headers.
- The threshold is specific to this embedding model and chunking method. If either changes, re-run `scripts/embedding_bench/threshold.py` and re-select the value.
- The questions were written for the benchmark (with AI assistance). Re-measure in the Milestone E evaluation; also add "incomplete answer" and "summary" question types there.

## Sources

- [LangModule/ingestlib](https://github.com/LangModule/ingestlib) (`operations/split/segmenter.py`, `splitter.py`).
  - Structure-aware blocks, with headings bound to their content.
  - Chunks under 50 tokens merge into a neighbour.
  - Sections up to 700 tokens stay whole; the hard limit is 768 tokens.
  - A `[category › section › heading]` breadcrumb is prepended to the embedded text.
- [Anthropic: Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval). Prepending 50–100 tokens of chunk-specific context reduced top-20 retrieval failures by 35%.
- Chunking benchmark summaries ([premai.io](https://blog.premai.io/rag-chunking-strategies-the-2026-benchmark-guide), [firecrawl.dev](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)).
  - Common defaults are 256–512 tokens with 10–25% overlap.
  - Differences between recursive, semantic and LLM-based splitting are a few points of recall.
  - Over-fragmented chunks hurt.
  - These figures were read from secondary summaries, not the original reports.
