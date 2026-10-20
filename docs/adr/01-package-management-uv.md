# ADR-01: Package management with uv and a publish-date cut-off

- **Status:** Accepted
- **Date:** 2026-10-19 (cut-off added 2026-10-20). Recorded retroactively on 2026-10-20.

## Context

The project must install the same way on any machine, primarily Windows with PowerShell. Without a lock file, `pip install` resolves "latest compatible" versions on every run, so two installs a week apart can behave differently. The project also wanted to avoid package versions published only days earlier, which have had the least real-world use.

## Options considered

| Option | Notes |
|---|---|
| `pip` + `requirements.txt` | No built-in lock file with hashes; dev and runtime dependencies are usually split by convention. |
| Poetry | Lock file and dependency groups; a separate tool with its own resolver and install step. |
| **uv** | `pyproject.toml` + `uv.lock`, dependency groups, manages the virtual environment and Python version, and runs commands with `uv run`. Fast and works the same in PowerShell. |

## Decision

1. **Use uv.** Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`, which is committed. Commands run through `uv run` (for example `uv run pytest`), so they always use the project's environment.
2. **Dependency groups:**

   | Group | Packages | Installed by |
   |---|---|---|
   | runtime | `dependencies` | default |
   | `dev` | test tools (`pytest`, `httpx2` for Starlette's `TestClient`) | default |
   | `bench` | benchmark-only packages (`psutil`) | only with `--group bench` |

3. **Publish-date cut-off.** `[tool.uv] exclude-newer = "2026-10-05T00:00:00Z"` makes the resolver ignore any version published after that date.
   - When it was introduced, 13 locked packages moved to earlier versions (for example FastAPI 0.149.0 → 0.142.2, SQLAlchemy 2.1.5 → 2.1.3).
   - No code changes were needed: all tests passed and pyright reported no errors.

## Consequences

**Gains**

- Reproducible installs: `uv sync` recreates the exact environment from `uv.lock`.
- A single tool for the virtual environment, dependencies and running commands.

**Accepted costs**

- A new dependency can only be used in a version released before the cut-off. Moving the cut-off is a deliberate change: update the date, run `uv lock`, re-run tests.
- Security fixes released after the cut-off are not picked up automatically. For a local demo this is acceptable. A deployed system would need a regular update policy.

**Revisit when** a needed fix or feature exists only in a version newer than the cut-off.
