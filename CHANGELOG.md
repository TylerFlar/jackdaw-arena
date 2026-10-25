# Changelog

## Unreleased

### Added
- The agent protocol (`/api/v1`): start episodes on server-held seeds, step them in batches, resume and forfeit, with idempotent retries and per-agent budgets.
- The episode engine: exact rebuilds from the stored trace, a shadow run recording the canonical tape, and end-of-episode verification.
