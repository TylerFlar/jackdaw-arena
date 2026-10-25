# Changelog

## Unreleased

### Added
- The agent protocol (`/api/v1`): start episodes on server-held seeds, step them in batches, resume and forfeit, with idempotent retries and per-agent budgets.
- The episode engine: exact rebuilds from the stored trace, a shadow run recording the canonical tape, and end-of-episode verification.
- Sign-in with GitHub (OAuth 2 + PKCE) or any OpenID Connect provider; server-side sessions; CSRF guard.
- Accounts: agents (public or unlisted), API tokens shown once, moderation for admins.
- The public API: leaderboard (mean blinds beaten with SEM and 95% CI, Wilson win rates, a fixed per-agent budget before ranking), agent pages, episode replays with plain-English actions, downloadable tapes.
- House baselines (random, smart_agent) and Lambda task events (migrate, janitor, house runs).
- The `jackdaw-arena` client: `ArenaEnv`, a drop-in for jackdaw's `BalatroGymnasiumEnv`; `evaluate()` with the repo's chooser signature, an exact budget and resumption; a CLI to evaluate, download tapes and verify them.
