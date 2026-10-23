# 08 — Server-owned conversation context with an input budget

**Status:** Accepted  
**Date:** 2026-10-22

## Context

The first follow-up implementation accepted up to four prior user questions from Streamlit. It did not include assistant replies, persisted nothing, and could not independently verify that a previous answer remained authorized after a document changed status or visibility.

## Options considered

1. Continue sending client-side text with a larger fixed turn count.
2. Store conversations in SQLite, send only a conversation ID, and select prior exchanges for each request.

## Decision

Use SQLite conversations owned by a user. `/chat` creates a conversation on the first successful exchange and accepts only an optional conversation ID on later requests. Prior user and assistant messages are read by the server. Each assistant message stores both its cited sources and every document that was given to the model as context, because an answer can carry facts from a chunk it did not cite. Before using an old exchange in a prompt, all of those documents are checked against the current user's SQLite ACL; an exchange with any revoked document is excluded, and an evidence-based answer with no recorded documents is treated as unverifiable. Refusals and canned social replies are not used as context, since they cannot resolve a follow-up and would pollute retrieval. `[S#]` labels are stripped from history before prompting: they referred to the previous turn's sources, and the same number means a different chunk in the current turn. History display redacts such answers. The current turn always runs fresh ACL-filtered retrieval, and only current source chunks are evidence.

The model's configured context limit, output allowance, application input cap, and history cap determine the prompt budget. For now, UTF-8 byte length plus fixed overhead is a conservative upper bound on BPE content tokens, so the app may include less history than the provider permits. Newest complete user/assistant exchanges are included first. Source chunks take priority over history; low-ranked sources are trimmed if even the current question plus evidence exceeds the input cap.

## Consequences

Follow-ups can refer to earlier answers across browser sessions, while one user's conversation ID cannot read another user's history. The API no longer trusts client-supplied history. The local demo gains two SQLite tables without a migration of existing rows. Token use is deliberately conservative; a model-specific tokenizer and summary strategy can be revisited after evaluation. Conversations are retained until a future deletion/retention policy is implemented.

## Evidence

Tests cover ownership, persistence, ACL revocation, history selection, and Streamlit's ID-only request flow. The configured default model context limit should be rechecked when changing providers or models.

Retrieval query strategy was measured on doc2dial v1.0.1 (IBM, CC BY 3.0; DMV domain, 149 documents, 908 follow-up turns). Appending the previous user question and the start of the previous answer put the right document first in 67.0% of turns, versus 52.5% with only the previous question, 33.1% with the bare question and 40.0% with an LLM rewrite (60-turn sample). The current strategy is kept. Known limits: doc2dial dialogues stay on one document, so topic switches (where history can pull in the previous topic, see `eval/conversations.jsonl` F07) are not covered, and history raises similarity scores, which weakens the 0.80 threshold as a first refusal layer. Results: `eval/results/doc2dial-dmv-2026-10-22.json`, `eval/results/followup-current-2026-10-22.json`.

The history window was measured as well (`scripts/doc2dial_eval.py`, cached corpora). On doc2dial, where a dialogue stays on one document, using the last 4 or 6 turns raised first-rank document accuracy to 75.2% and 77.5%. A stress test on the synthetic set, with 1–3 unrelated earlier exchanges placed before the follow-up, showed the opposite: first-rank accuracy fell from 100% to 57% (4 turns) and 47% (6 turns) for elliptical questions, while top-5 stayed near 100%. Mixed-topic conversations are the normal case for a company assistant, so the window stays at the last two turns (one exchange, 300 characters each). The character limit had no measurable effect. Because the right document is almost always in the top five but not always first, re-ranking is the next lever to evaluate.

**Update (2026-10-23): topic switches.** A live session showed the known limit: after a VPN exchange, "office kuralları neler" retrieved four VPN chunks and the model correctly answered with the fixed refusal, although the user could read the answer. Follow-up turns now run two ACL-filtered searches, the history query above and the bare question, fused with Reciprocal Rank Fusion (k = 60); the first turn of a conversation still runs one search. Each chunk keeps the dense score of the query that found it, so the 0.80 threshold is unchanged. Measured with the product's hybrid search (one-off script, query embeddings on GPU):

| | History query | Bare question | Fused |
|---|---|---|---|
| doc2dial: right document first | **71.6%** | 36.0% | 66.1% |
| doc2dial: right document in top 5 | **91.5%** | 57.7% | 89.4% |
| doc2dial: answer span in top 5 | 68.6% | 51.7% | **73.2%** |
| Turkish set, topic switch first (with 1–3 unrelated earlier exchanges) | 33% (9/27) | 100% | **100% (27/27)** |
| Turkish set, elliptical follow-up first | **100% (72/72)** | 62.5% | 87.5% (63/72) |
| Turkish set, elliptical follow-up above threshold in top 5 | 100% | 62.5% | 100% |
| Refusal turns where a chunk passes the threshold | 5/5 | 3/5 | 5/5 |

Fusion trades about two points of document recall on single-topic doc2dial dialogues for fixing topic switches, and the model sees more of the answering passage. Down-weighting the bare question (0.5, 0.3) cannot bring a new chunk into the top five (rank 1 at weight 0.5 scores below rank 5 of the history query), so it changes only the order and leaves the reported case unsolved; equal weights were chosen. The extra search costs one query embedding (median 40 ms on the development CPU) and one Qdrant search. Tests cover a topic switch that the history query alone misses, a single search without history, and the ACL on both searches; disabling fusion makes them fail.
