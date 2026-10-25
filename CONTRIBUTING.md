# Contributing

Thanks for helping. This page covers the branches, what a pull request needs and how a release is
cut, then the layout, the everyday commands, running your own copy of the site, its game art and
upgrading jackdaw. The flow is jackdaw's own.

## Branches

| branch | holds | pull requests from |
|---|---|---|
| `main` | the releases: each release is a merge from `dev`, tagged `vX.Y.Z` and deployed | `dev` (a release) or `hotfix/*` |
| `dev` | the next release | your branch |

**Open pull requests against `dev`**, the repository's default branch: branch from `dev`, and a
new pull request targets it. A required check (`pr-target`) fails any pull request into `main`
from another branch; if it fails on yours, change the base to `dev` (Edit, next to the title).

`main` only moves at a release, and the Deploy workflow releases every push to it whose CI passes.
Installing the client from `main` gets the latest release
(`uv add "jackdaw-arena @ git+https://github.com/TylerFlar/jackdaw-arena@main#subdirectory=client"`,
or `@vX.Y.Z` for a given one); an install from the bare URL gets `dev`.

## A pull request

CI runs on every pull request: the version check; ruff and the API's tests, the slow statistical
ones included; the client's tests on Python 3.10 and 3.13; the site's lint, types and tests; the
Terraform checks; the Lambda image; and the end-to-end tests, under the production CSP. The tests
against a real Aurora DSQL cluster run on `main`, before a release deploys. Before you push:

```bash
(cd api && uv run pytest && uv run ruff check . && uv run ruff format --check .)
(cd client && uv run pytest)
(cd web && pnpm test && pnpm lint && pnpm typecheck)
```

- **API changes** regenerate the site's types (`cd web && pnpm openapi`): CI fails on a stale
  `openapi.json`.
- **Schema changes** are new numbered migrations in `api/src/arena/db/migrations/`, and only
  expand: the live version keeps running on the new schema while a release migrates.
- **Changes users see** get a line under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).
- Pull requests into `dev` can be squash-merged.

## Cutting a release

1. **On `dev`**, set the version:
   - rename CHANGELOG.md's "Unreleased" section to `## [X.Y.Z] - YYYY-MM-DD` and start a new,
     empty "Unreleased" above it;
   - set the version in `api/pyproject.toml`, `api/src/arena/__init__.py`,
     `client/pyproject.toml`, `client/src/jackdaw_arena/__init__.py` and `web/package.json`;
   - refresh the lock files: `uv lock` in `api/` and in `client/`;
   - check: `python scripts/check_version.py`.
2. **Open a pull request from `dev` to `main`** named "Release X.Y.Z", and merge it with a merge
   commit (not squash or rebase, so `main` and `dev` keep one history). The merge is the deploy:
   CI runs on `main`, the DSQL tests included, then the Deploy workflow releases it (auditing the
   season first when the jackdaw release changed).
3. **Tag the merge commit** on `main` and push the tag:

   ```bash
   git switch main && git pull
   git tag -a vX.Y.Z -m "Jackdaw Arena X.Y.Z"
   git push origin vX.Y.Z
   ```

   The Release workflow checks the tag against the version, builds the client's wheel and sdist,
   and opens a draft GitHub release with them and the changelog section. Publish it from the
   releases page.
4. **Bring `dev` up to `main`:** `git switch dev && git merge --ff-only main && git push`.

Versions follow [semantic versioning](https://semver.org). While the version is 0.x, a release
that breaks something (the agent protocol, the client's API) bumps the minor version
(0.1.0 → 0.2.0), and a release of fixes only bumps the patch version (0.1.0 → 0.1.1).

A fix that can't wait for the next release goes on a `hotfix/<name>` branch from `main`, with the
patch version bump and a changelog entry; open its pull request against `main` (merging it
deploys), tag it as above, then merge `main` into `dev`. A fix to the docs or the workflows alone
needs no version or tag.

## Layout

```
api/      the service: FastAPI, SQLAlchemy Core, psycopg 3, jackdaw; its Dockerfile and tests
client/   the jackdaw-arena package: ArenaEnv, evaluate() and the CLI
web/      the site: React, TypeScript, Vite, TanStack Query (API types generated from the OpenAPI)
infra/    bootstrap/ (the Terraform state bucket), terraform/ (everything else), scripts/
scripts/  check_version.py: the version is the same everywhere
.github/  the CI, PR target, Deploy, Release and Uptime workflows
```

The site runs on AWS:

- CloudFront serves the React app from S3, and sends `/api` and `/auth` to a Lambda function (`arena-api`).
- A second function from the same image (`arena-tasks`) runs migrations, the idle-episode janitor and the house baselines.
- The data is in Aurora DSQL.

## Development

You need [uv](https://docs.astral.sh/uv/), Node 24 with pnpm 10, and Docker.

```bash
docker compose up -d db                        # PostgreSQL 16 on 127.0.0.1:54329
(cd api && uv run pytest)                      # add -m slow for the statistical baseline runs
(cd client && uv run pytest)
(cd api && uv run arena migrate && uv run arena serve)       # the API on :8000
(cd web && pnpm install && pnpm dev)                         # the site on :5173, proxying /api and /auth
(cd web && pnpm test && pnpm lint && pnpm typecheck)
(cd web && pnpm openapi)                       # regenerate the API types after changing the API
```

To work on the site against real data, point the dev server at the live API: `ARENA_API_URL=https://arena.tylerflar.com pnpm dev`.

The end-to-end test runs the production image behind Caddy, which stands in for CloudFront, with a mock OpenID provider standing in for GitHub:

```bash
(cd web && pnpm build)
docker compose --profile e2e up -d --build --wait
(cd web && pnpm e2e)
docker compose --profile e2e down -v
```

The infrastructure checks need no AWS account, because the tests mock the providers. They need Terraform 1.17 or later:

```bash
cd infra/terraform
terraform init -backend=false && terraform validate && terraform test
tflint --init && tflint
```

## Running your own

Terraform creates the resources, and `infra/scripts/deploy.py` releases code into them. The Deploy workflow runs it on every green push to `main`.

1. **State bucket:** run `terraform -chdir=infra/bootstrap init && terraform -chdir=infra/bootstrap apply`. Then copy `infra/terraform/backend.hcl.example` to `backend.hcl` and run `terraform -chdir=infra/terraform init -backend-config=backend.hcl`.
2. **DNS:** copy `terraform.tfvars.example` to `terraform.tfvars`, then run `terraform apply -target=aws_route53_zone.arena`. At your parent domain's DNS host, add the four `name_servers` as NS records for the subdomain.
3. **Sign-in:** create a GitHub OAuth App with the callback `https://<domain>/auth/callback/github`, then run `infra/scripts/set-secrets.ps1` yourself. It stores the client ID and secret in SSM Parameter Store.
4. **First image, then everything:**
   - `terraform apply -target=aws_ecr_repository.api`
   - build and push `api/` for `linux/amd64`, tagged with the commit
   - set `api_image_uri`, then run `terraform apply`

   CloudFront takes 5–15 minutes. If you set `alert_email`, confirm the two SNS emails.
5. **Release:** `uv run infra/scripts/deploy.py`. It migrates the database, audits the season when the jackdaw release changes (see [Upgrading jackdaw](#upgrading-jackdaw)), publishes a version and health-checks it, then moves the `live` alias. It uploads the site and smoke-tests it, moving the alias back if anything fails. `--rollback` moves it back by hand.
6. **CI/CD:**
   - Set the `github_variables` output as repository variables.
   - Create a `production` environment limited to `main`.
   - Run the house baselines, `random` and `smart`:

     ```bash
     aws lambda invoke --function-name arena-tasks --cli-binary-format raw-in-base64-out \
       --cli-read-timeout 900 --payload '{"task":"house","agent":"smart","episodes":500}' house.json
     ```

Function settings changed in Terraform (memory, environment) take effect at the next release, when a new version is published.

## Game art

The site draws cards, jokers, blinds and tags with Balatro's own sprites, and headings in its font. They belong to LocalThunk (the font is Daniel Linssen's m6x11), so they're never committed: `web/.art/` is ignored, and builds don't include it. Without them, the site draws plain cards.

```bash
uv run infra/scripts/extract_art.py ".../steamapps/common/Balatro/Balatro.exe"   # into web/.art/v1/
uv run infra/scripts/upload_art.py              # to the site's bucket, under art/
```

`pnpm dev` serves `web/.art/` at `/art/`. The files are cached for good, so changed files go in a new folder: bump `VERSION` in `extract_art.py` and `ART_ROOT` in `web/src/art/art.ts`.

## Upgrading jackdaw

The API pins one jackdaw release in `api/pyproject.toml`: the version, and the release's five wheel URLs. Each episode records the release that played it, and belongs to a season: the releases that play the same game, listed in `api/src/arena/engine/spec.py`. The API won't start on a release its season doesn't list.

**A release that keeps the rules**, so that a seed plays the same run (jackdaw's changelog says so):

1. Add it to the current season's `engines`.
2. Update the pin and the wheel URLs, then run `uv lock`.
3. Release as usual. When the release changes, the deploy replays every ended episode of the season with it before it takes traffic, and stops if any of them ends in a different state.

The audit also runs by hand:

```bash
aws lambda invoke --function-name arena-tasks --cli-binary-format raw-in-base64-out \
  --cli-read-timeout 900 --payload '{"task":"audit"}' audit.json
```

**A release that changes the rules:** add a `Season` with a new key, and point `SEASON` at it. The new season's leaderboard starts empty, and every agent gets a fresh budget. The new release can't replay the old season's episodes, so the site stops showing those replays; their tapes can still be downloaded.
