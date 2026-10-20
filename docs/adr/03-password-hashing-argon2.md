# ADR-03: Password hashing with Argon2 (pwdlib)

- **Status:** Accepted
- **Date:** 2026-10-20. Recorded retroactively on 2026-10-20.

## Context

Demo accounts log in with an email and a password. Passwords must never be stored in a form that can be turned back into the password, and a stolen database file should be expensive to attack.

Two further risks come from the login endpoint itself:

- **User enumeration:** different responses for "unknown email" and "wrong password" reveal which emails have accounts.
- **Timing:** checking a password hash takes noticeable time. If unknown emails return immediately, the response time alone reveals which emails exist.

## Options considered

| Option | Notes |
|---|---|
| Plain or fast hash (SHA-256) | Rejected. Fast hashes let an attacker try billions of guesses per second against a stolen database. |
| bcrypt (e.g. via passlib) | Proven, deliberately slow. Has a 72-byte password input limit. |
| **Argon2 via `pwdlib`** | Memory-hard password hash (Argon2id). It is expensive in both CPU and RAM, which also slows down GPU-based guessing. Small, focused library. |

## Decision

1. **`pwdlib` with `PasswordHash.recommended()`**, which uses Argon2id.
   - Every hash gets a random salt, so equal passwords produce different hashes.
   - Stored hashes start with `$argon2id$` (verified on the seeded accounts).
2. **The same response for every login failure.** Unknown email, wrong password and inactive account all return HTTP 401 with the same message.
3. **Constant work for unknown emails.** When the email does not exist, the password is still verified against a fixed dummy hash (`DUMMY_PASSWORD_HASH`). Response time therefore does not reveal whether the account exists.
4. **No password in code.**
   - The demo password is read from `.env` (`DEMO_USER_PASSWORD`) and has no default.
   - The seed script refuses to run if the password is missing or is still the `.env.example` placeholder.
   - `.env` is gitignored.

## Consequences

**Gains**

- A stolen database exposes only salted Argon2 hashes.
- The login endpoint does not reveal which emails are registered, neither through its messages nor through its timing.

**Accepted costs**

- Each login spends deliberate CPU time and memory on hashing. That is the point, and it is negligible for a demo.
- Re-running the seed does not change the password of existing accounts. Changing the demo password means deleting the database or updating the users.

**Not covered:** login rate limiting and account lockout after repeated failures. They are outside the MVP scope and are to be listed in the README as known limitations.
