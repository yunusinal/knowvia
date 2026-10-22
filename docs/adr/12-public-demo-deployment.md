# 12 — Public demo: one container behind Caddy on Oracle Always Free

**Status:** Accepted  
**Date:** 2026-10-23

## Context

The project owner wants a live demo reachable on the internet. The app needs about 3–4 GB of RAM (multilingual-e5-large alone is 2.3 GB on disk), a persistent disk for SQLite and the Qdrant local folder, and a single process because Qdrant local mode locks its folder. Serverless platforms (Vercel, Cloud Run) and small free tiers (512 MB) do not fit; Oracle Cloud Always Free offers an ARM (Ampere A1) VM with enough memory at no cost. Until now the app was designed as a local demo, so going public adds risks: anyone could use a published admin account to upload or delete documents, a single visitor could exhaust the LLM provider's per-minute quota (Groq free tier: 8000 tokens per minute), and visitor data would accumulate.

## Options considered

1. Separate containers for API and Streamlit, with Qdrant as its own server.
2. One container running both processes, a named volume for data, Caddy in front for HTTPS.
3. A platform-as-a-service with persistent disks (Railway, paid Render) instead of a VM.

## Decision

Option 2 on an Oracle Always Free Ampere VM, chosen by the project owner.

**Image.** `python:3.12-slim-bookworm` with uv; dependencies come from `uv.lock` without the test and benchmark groups, so the same versions run locally and on ARM. The container runs as a non-root user. An entrypoint seeds users and documents (idempotent) before the API starts, because the seeders and the API cannot open the Qdrant folder at the same time; then it starts uvicorn on `127.0.0.1:8000` with one worker and Streamlit on `0.0.0.0:8501`, and exits if either process stops so the restart policy restarts both. Data and the model cache live in the `/data` volume. With `WARMUP_ON_START=true` the API loads the embedding and BM25 models and Qdrant before serving; without it the first question after a restart waited about 60 s for the model to load. `.dockerignore` keeps `.env`, runtime data, tests, evaluation files and the local agent and context files out of the image.

**Network.** Only Caddy publishes ports (80 and 443) and obtains and renews a Let's Encrypt certificate for `KNOWVIA_DOMAIN`. The Streamlit port is reachable only from Caddy; the API is reachable only from inside the container.

**Public-demo protections.**

- `ADMIN_PASSWORD` gives the admin its own secret password; the seeder replaces an existing admin password that does not match it, so an admin created earlier with the shared member password does not keep it. The landing page shows member accounts and `KNOWVIA_PUBLIC_DEMO_PASSWORD`, never the admin.
- Sliding-window limits per minute: chat per user (8) and across all users (20), login per e-mail address (10). Browsers reach the API through the Streamlit server, so the API never sees visitor IP addresses; keys are user, e-mail and a global counter instead of IP. Counters are in memory, which matches the single-process design. Exceeded limits return 429 with `Retry-After`.
- `scripts/reset_demo.py` deletes conversations, messages and support tickets and keeps users and documents; the guide schedules it nightly with cron.

## Consequences

The whole demo runs on one free VM with two containers and a single `.env` file. Limits are shared by everyone using the same demo account, which is acceptable because their purpose is to protect the provider quota and the admin password, not fairness between visitors. Restarting the container resets the counters. Upgrades are `git pull` plus `docker compose up -d --build`. Scaling beyond one process would require moving Qdrant to a server and the counters to shared storage (master plan F8). Oracle reduced the Always Free ARM allowance in 2026 and may reclaim idle instances, so the host is a convenience, not a guarantee.

## Evidence

Tests: per-user and global chat limits with `Retry-After`, unauthenticated requests not consuming the global quota, per-e-mail login limits that also block the correct password and normalize case and spaces, a separate admin password replacing an old shared one, the reset keeping users and documents, the landing page listing member accounts but never the admin, and warm-up running only when enabled. Mutation checks removing the chat limit, the e-mail normalization, the admin password replacement or the shared global key each made a test fail. The image was built and run locally: first start seeded 4 users and 13 documents, a restart reused the volume without reseeding, a real question answered through the container, the eighth chat per minute was allowed and the ninth returned 429, and with warm-up the first question after a restart took 1.3 s instead of 61 s. These runs were on x86_64. `uv.lock` contains aarch64 wheels for every native dependency (onnxruntime, py-rust-stemmers, tokenizers, argon2, numpy), but an arm64 run under QEMU emulation crashed with a segmentation fault inside the emulator, so ARM is verified on the real Oracle A1 server instead (step 6 of `docs/deploy-oracle.md`).
