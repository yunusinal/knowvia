# 09 — Support tickets: the model proposes, the user confirms

**Status:** Accepted  
**Date:** 2026-10-22

## Context

User story US-07 asks for a support ticket when the documented steps do not solve a problem, but only with the user's approval. The ticket is created from a conversation that may include document text, and documents are untrusted input: a document could tell the model to "open a ticket". The master plan also asks that tool calling is used only if the provider supports it and is not marketed as an autonomous agent.

## Options considered

1. Detect "open a ticket" with rules and fill the ticket without the model.
2. Let the model call `create_support_ticket` and create the ticket immediately.
3. Let the model call `create_support_ticket` only to draft a ticket; the app shows the draft and creates it after the user confirms with a separate request.

## Decision

Option 3. The grounded RAG call offers one tool, `create_support_ticket(subject, description)`, through the OpenAI-compatible `tools` parameter (Groq documents tool use for `openai/gpt-oss-120b`). The adapter accepts only a call to a tool that was offered, with a JSON object as arguments; anything else is ignored. A valid call becomes a `ticket_proposal` in the `/chat` response, and the answer text is a fixed message, so the model's own wording cannot claim that a ticket exists. Nothing is written to the tickets table at that point.

Streamlit shows the draft with editable subject and description and two buttons. Only "Talebi oluştur" calls `POST /support-tickets`; ownership comes from the token, the request rejects unknown fields, and a linked conversation must belong to the caller. A new question discards an unconfirmed draft. `GET /support-tickets` returns a member's own tickets and every ticket for an admin.

The tool is offered only when retrieval found evidence above the threshold, so a first message such as "open a ticket" with no matching documents still gets the standard refusal. Tickets are stored locally; there is no real helpdesk integration.

## Consequences

The user always sees and can edit what will be filed, which also contains prompt-injection attempts that try to trigger the tool. One extra request and one click are needed per ticket. Providers without tool calling simply never return a proposal, and answers work as before. Tickets have no status workflow yet beyond `open`.

## Evidence

Tests cover: the tool offered in the grounded call, a proposal that creates no row until confirmation, member and admin visibility, linking to another user's conversation (404), rejected client fields such as `created_by`, ignored unoffered or malformed tool calls, truncation of long arguments, and the Streamlit confirm, cancel and discard flows. Mutation checks on ownership filtering, conversation ownership, tool-name validation and tool offering each made a test fail. A live run with `openai/gpt-oss-120b` drafted a ticket only after "I tried the clock and cache, it still fails, can you open a ticket?", and not for ordinary follow-up questions.
