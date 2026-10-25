# Changelog

All notable changes to Jackdaw Arena: the site, its API and the `jackdaw-arena` client. The
version follows [semantic versioning](https://semver.org); while it is 0.x, a minor release
(0.1 → 0.2) can break things, and a patch release only fixes them.

## Unreleased

## [0.1.0] - 2026-10-25

The first release: the site at [arena.tylerflar.com](https://arena.tylerflar.com), its API, and
the client. Install the client from `main`, which only moves at a release, or from a tag.

### Added
- The agent protocol (`/api/v1`): start episodes on server-held seeds, step them in batches, resume and forfeit, with idempotent retries and per-agent budgets.
- The episode engine: exact rebuilds from the stored trace, a shadow run recording the canonical tape, and end-of-episode verification.
- Sign-in with GitHub (OAuth 2 + PKCE) or any OpenID Connect provider; server-side sessions; CSRF guard.
- Accounts: agents (public or unlisted), API tokens shown once, moderation for admins.
- The public API: leaderboard (mean blinds beaten with SEM and 95% CI, Wilson win rates, a fixed per-agent budget before ranking), agent pages, episode replays with plain-English actions, downloadable tapes.
- House baselines (random, smart_agent) and Lambda task events (migrate, janitor, house runs).
- Balatro's sprites and font on the site when it has them: `infra/scripts/extract_art.py` copies them from a copy of the game, and `upload_art.py` publishes them to the site's bucket. They're never in the repository. Without them the site draws plain cards. `/api/catalog` gives each key's sprite cell, and stakes.
- Replays on a Balatro board: each action plays out, a hand's cards scoring one by one with their chips, mult and money as the game shows them (jackdaw 0.2.2's scoring events, served by `/api/episodes/{id}/replay`), at 1×, 2×, 4× or instantly; the old text view stays a click away. The episode page leads with the result, and its seed, final state and jackdaw release sit under Run details.
- Agent pages by track, in the leaderboard's terms; account pages name tracks.
- Seasons: the jackdaw releases that play the same game. Each episode records the release that played it, and a deploy that changes the release first replays the season's ended episodes with it (the audit task).
- The website: a leaderboard by track (tabs), with the baselines among the agents and the ones still playing below, agent pages with stat tiles and a blinds-beaten histogram, a step-by-step replay viewer (keyboard, playback, action log), a getting-started guide with how scores work, and account pages for agents and tokens. Light and dark themes, and phone layouts.
- One container image for Lambda and local Docker (the Lambda Web Adapter as an extension), and a docker compose stack that stands in for AWS in end-to-end tests: Caddy for CloudFront, a mock OpenID provider for GitHub.
- The `jackdaw-arena` client: `ArenaEnv`, a drop-in for jackdaw's `BalatroGymnasiumEnv`; `evaluate()` with the repo's chooser signature, an exact budget and resumption; a CLI to evaluate, download tapes and verify them.
- Terraform for AWS, serverless end to end:
  - CloudFront in front of a private S3 site and the API's Lambda function URL, with a strict CSP and HSTS, and edge caching only for public reads.
  - Aurora DSQL, with a scratch cluster for CI and daily backups.
  - A Route 53 zone with CAA records, and a DNS-validated ACM certificate.
  - EventBridge Scheduler for the janitor and keep-warm pings.
  - Email alarms and a monthly budget.
  - OIDC roles for GitHub Actions.
  - Offline tests with a mocked provider, and tflint.
- Releases with `infra/scripts/deploy.py`: migrate, publish, health-check the new version, move the `live` alias, upload the site, smoke-test, and move back on failure. `--rollback` is the manual version of that last step.
- Releases as in jackdaw: pull requests go to `dev`; `main` takes the release merges (deployed) and hotfixes, tagged `vX.Y.Z`; a tag drafts a GitHub release with the client's wheel and sdist.
- GitHub Actions:
  - CI: the API, the client on Python 3.10 and 3.13, the site, the infrastructure, the Lambda image, end-to-end tests, and DSQL tests on `main`.
  - Deploy: every green push to `main`.
  - Uptime checks.
- API responses over 1 KB are gzip-compressed, and the API refuses to start in production on development defaults.
