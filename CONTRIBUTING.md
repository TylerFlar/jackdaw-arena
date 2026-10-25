# Contributing

## Layout

```
api/      the service: FastAPI, SQLAlchemy Core, psycopg 3, jackdaw; its Dockerfile and tests
client/   the jackdaw-arena package: ArenaEnv, evaluate() and the CLI
web/      the site: React, TypeScript, Vite, TanStack Query (API types generated from the OpenAPI)
infra/    bootstrap/ (the Terraform state bucket), terraform/ (everything else), scripts/
.github/  the CI, Deploy and Uptime workflows
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
