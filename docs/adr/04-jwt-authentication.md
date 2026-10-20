# ADR-04: Stateless JWT bearer tokens, authority stays in the database

- **Status:** Accepted
- **Date:** 2026-10-20. Recorded retroactively on 2026-10-20.

## Context

After login, every protected API call must identify the user. The rest of the system decides what that user may see. It is an access-aware knowledge assistant, so the role and the department must come from a trusted source. A value the client can edit is never trusted.

The API is used by a Streamlit UI and by FastAPI's interactive `/docs` page.

## Options considered

| Option | Notes |
|---|---|
| Server-side sessions with a cookie | Simple to revoke, but needs a session store. Cookie handling is awkward between a Streamlit UI and a separate API. |
| **Signed JWT access token (Bearer)** | Stateless: the API verifies a signature, with no session table. Works directly with FastAPI's OAuth2 password flow and the `/docs` "Authorize" button. |
| JWT carrying role and department ("claims") | Saves a database read per request. Rejected: a role change or deactivation would not take effect until the token expires, and authorization data would live in two places. |

## Decision

1. **Login:** `POST /auth/login` with the standard OAuth2 password form: `username` holds the email, plus `password`. It returns `{access_token, token_type: "bearer"}`.
2. **Token contents:** only `sub` (user id) and `exp` (expiry, 60 minutes, configurable). There is no role, department or admin flag in the token.
3. **Signing:** PyJWT with HS256. The algorithm is pinned when decoding. The token's own `alg` header is never trusted, which closes the "algorithm confusion" class of attacks.
4. **The secret is mandatory.**
   - `JWT_SECRET_KEY` has no default and must be at least 32 characters.
   - If it is missing, the application refuses to start (fail closed).
   - Settings errors are configured not to print `.env` values.
5. **Every protected request reloads the user from SQLite** (`get_current_user`). Role and department come from the database row. A deactivated or deleted user is rejected even while holding a token that has not yet expired.
6. **Uniform errors.** An invalid signature, an expired token, an unknown user and an inactive user all return the same 401 response.

## Consequences

**Gains**

- One authority for identity and permissions (SQLite).
- Deactivating a user takes effect immediately, on the next request.
- No session store.
- The `/docs` page can be used to test the protected endpoints.

**Accepted costs**

- **One database read per request.** Negligible for SQLite in a local demo.
- **No refresh tokens.** The user logs in again after 60 minutes.
- **No server-side logout or token revocation list.** "Logout" means the client discards the token. Immediate deactivation still works through the database check.
- **HS256 uses one shared secret** for signing and verifying. That is appropriate for a single service; separate verifying services would call for an asymmetric algorithm (e.g. RS256 or EdDSA).

**Revisit when** another service must verify tokens, or when sessions longer than an hour are needed.
