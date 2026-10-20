# ADR-02: Application database with SQLite and SQLAlchemy 2.0

- **Status:** Accepted
- **Date:** 2026-10-19. Recorded retroactively on 2026-10-20.

## Context

Knowvia needs a relational store for users and, later, documents, document status and access rules. This store is the **single source of truth for authorization**: who may see which document is decided from it, never from the client or the vector database.

The project is a local demo, so it should run with no database server to install. It should still use patterns that carry over to a production database.

## Options considered

| Option | Notes |
|---|---|
| PostgreSQL | Production-grade, but requires a running server for anyone trying the demo. Kept as a future migration target. |
| SQLite with the standard `sqlite3` module | No dependency, but hand-written SQL and manual row-to-object mapping. |
| **SQLite + SQLAlchemy 2.0** | One file on disk, no server. Typed ORM models (`Mapped[...]`), and the same code can target PostgreSQL by changing the connection URL. |

## Decision

1. **SQLite file** at `data/runtime/app.db`, configurable with `DATABASE_URL`. The `data/runtime/` folder is gitignored, so the database is never committed.
2. **SQLAlchemy 2.0 typed models.** For example, `User` has:
   - a UUID string primary key,
   - a unique email,
   - a password hash,
   - a role and a department,
   - an `is_active` flag,
   - a timezone-aware `created_at`.
3. **Enums are strict.** `Role` and `Department` are stored as their values (`"admin"`, `"IT"`, …). They are validated twice: in Python (`validate_strings=True`) and by a database `CHECK` constraint. An invalid role cannot be written by either path.
4. **Database models and API schemas are separate.** API responses use Pydantic models (`UserOut`) that list exactly the fields to expose, so `password_hash` can never leak through a response by accident.
5. **One session per request** through a FastAPI dependency (`get_db`). Because each request opens and closes its own session, SQLite's same-thread check is disabled (`check_same_thread=False`).
6. **No migration tool.**
   - At startup, `init_db()` creates the folder and any missing tables (`create_all`). It never alters or drops existing ones.
   - The demo database is disposable and is rebuilt by deleting the file and re-running the seed script.

## Consequences

**Gains**

- Zero-install database.
- Typed, readable models checked by pyright.
- Invalid enum values are rejected at two layers.
- No accidental exposure of database-only fields.

**Accepted costs**

- **Schema changes are not migrated.** After changing a model, the local database file must be deleted and re-seeded. Fine for a demo; a real deployment would add Alembic.
- **SQLite allows one writer at a time.** That suits a single-process local demo. Concurrent production load would need PostgreSQL.
- **Tests use an in-memory SQLite database** shared through `StaticPool`. This is fast and isolated, but it is SQLite, not the future production engine.

**Revisit when** the demo must keep data across schema changes, or when moving to PostgreSQL.
