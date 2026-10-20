# ADR-06: Own recursive text splitter instead of langchain-text-splitters

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

Extracted document text must be split into chunks before embedding. ADR-05 fixes the constraints:

- **Size:** ~350 tokens per chunk with ~50 tokens of overlap.
- **Hard limit:** at most 512 tokens as counted by `multilingual-e5-large`'s own tokenizer, including the `passage: ` prefix and special tokens. Longer text is silently truncated and never becomes searchable.

The original plan was `RecursiveCharacterTextSplitter` from `langchain-text-splitters`, with the model tokenizer as its length function.

Two findings changed the decision:

1. **Dependency weight.** Resolving `langchain-text-splitters` 1.1.3 under the project's package cut-off pulls in about 15 extra packages for one class. Among them are `langchain-core`, `langsmith` (LangChain's tracing client), `websockets`, `orjson` and `zstandard`.
2. **Separator order matters for PDFs.** Testing with real Turkish PDFs (Edge and fpdf2 output) showed that extracted PDF text contains line breaks in the middle of sentences, because PDFs break at visual line ends. A splitter that tries `"\n"` before sentence ends cuts sentences in half.

## Options considered

| Option | Notes |
|---|---|
| `langchain-text-splitters` | Well known and configurable (custom separators, length function). Its default separator order is `"\n\n"`, `"\n"`, `" "`, `""`. Pulls in the LangChain core stack. |
| **Own recursive splitter** (~100 lines with docs) | Same algorithm, no new dependency. The separator order is explicit and tested. Fully readable. |
| Sentence segmentation library (e.g. NLP-based) | Better sentence detection, but it adds language models or data files for a marginal gain at this stage. |

## Decision

`app/services/chunking.py` implements a recursive splitter.

1. **Atomize.** If a text does not fit the budget, split it at the first separator that occurs in it, keeping the separator at the end of each piece. Repeat on pieces that are still too long with the next separators. Order:

   | Order | Separator |
   |---|---|
   | 1 | paragraph `"\n\n"` |
   | 2 | sentence end `". "`, `"? "`, `"! "` |
   | 3 | line `"\n"` |
   | 4 | `"; "`, `", "` |
   | 5 | word `" "` |
   | 6 | characters (last resort, binary search for the longest fitting prefix) |

2. **Merge.** Join pieces greedily until the next piece would exceed the budget.
3. **Overlap.** Start the next chunk with the longest tail of whole pieces that fits the overlap budget.
4. **Chunks never span pages,** so every chunk has an exact page number for citations. `chunk_index` is continuous across the document.
5. **Token counting is injected** (`count_tokens`). In production it is the embedder's `count_passage_tokens`, which uses a copy of the model tokenizer with truncation and padding disabled. The model's own tokenizer truncates at 512, which would hide an overflow.

## Consequences

**Gains**

- No LangChain dependency.
- Sentence-aware splitting that suits PDF text.
- Every rule is covered by tests:
  - separator preference,
  - overlap,
  - no text lost,
  - page boundaries,
  - the character fallback,
  - a real-tokenizer test asserting that no chunk exceeds 350 tokens.

  Mutation checks confirmed the tests fail when the separator order, the overlap or the non-truncating counter is broken.

**Accepted costs**

- We maintain the splitter ourselves.
- Sentence detection is punctuation based. Abbreviations such as "vb. " or "Dr. " can end a piece early. This is harmless for retrieval, but it is not linguistically exact.

**Known behaviour to evaluate**

Overlap is built from whole pieces. When a chunk boundary falls between paragraphs that each fit the budget, the last paragraph (typically 60–100 tokens) is larger than the 50-token overlap, so no overlap is added. Overlap does apply when a boundary falls inside a long paragraph.

This matches LangChain's behaviour. Whether always splitting to sentence level (which guarantees overlap at every boundary) improves retrieval will be measured in the Milestone E evaluation.

**Measured on the benchmark corpus:** 55 passages (12 790 characters, 3 090 tokens) became 11 chunks of 304–347 tokens, plus a final 57-token chunk.
