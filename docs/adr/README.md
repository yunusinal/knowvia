# Architecture Decision Records

This folder records the significant technical decisions behind Knowvia: what problem each decision solved, which options were considered, what was chosen and what trade-offs were accepted.

Each record is short and is written when the decision is made, so the reasoning is captured while it is fresh. A decision is never silently edited: if it changes, a new record supersedes the old one and the old one's status is updated.

## Format

Each ADR has the same sections:

- **Status:** `Accepted`, `Superseded by ADR-NN` or `Deprecated`
- **Context:** the problem and the constraints
- **Options considered**
- **Decision**
- **Consequences:** what we gain, what we accept, what to revisit
- **Evidence:** measurements or sources the decision relies on

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [01](01-package-management-uv.md) | Package management with uv and a publish-date cut-off | Accepted | 2026-10-19 |
| [02](02-sqlite-sqlalchemy.md) | Application database with SQLite and SQLAlchemy 2.0 | Accepted | 2026-10-19 |
| [03](03-password-hashing-argon2.md) | Password hashing with Argon2 (pwdlib) | Accepted | 2026-10-20 |
| [04](04-jwt-authentication.md) | Stateless JWT bearer tokens, authority stays in the database | Accepted | 2026-10-20 |
| [05](05-embedding-model.md) | Embedding model and runtime: `multilingual-e5-large` on fastembed (ONNX) | Accepted | 2026-10-20 |
| [06](06-own-text-splitter.md) | Own recursive text splitter instead of langchain-text-splitters | Accepted (merge strategy superseded by 07) | 2026-10-20 |
| [07](07-paragraph-chunking-and-threshold.md) | Paragraph-preserving chunking and a measured retrieval threshold | Accepted | 2026-10-21 |
| [08](08-server-owned-conversation-context.md) | Server-owned conversation context with an input budget | Accepted | 2026-10-22 |
| [09](09-support-ticket-propose-then-confirm.md) | Support tickets: the model proposes, the user confirms | Accepted | 2026-10-22 |

Numbers follow the order in which decisions were made. ADRs 01–04 were recorded retroactively, after the code they describe; from ADR-05 on, each record is written when its decision is made.
