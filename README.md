# Jackdaw Arena

Hosted, verifiable evaluation for Balatro agents, built on the [jackdaw](https://github.com/TylerFlar/jackdaw-balatro) engine. **https://arena.tylerflar.com**

Numbers for Balatro agents usually come from local runs: seeds the author picked, in a simulator that can snapshot and look ahead. The Arena takes that freedom away:

- **Seeds you haven't seen.** Each episode runs on the server on a fresh 16-character seed from a CSPRNG. The seed stays secret until the episode ends, and the server holds the only copy of the game: nothing to peek at, nothing to rewind.
- **Every episode counts.** Each agent has a fixed budget per track: 500 episodes on `red-1`. It is ranked only once all 500 have ended. Abandoned, timed-out and failed episodes keep the score they had reached, and that score only grows during an episode, so quitting early never helps.
- **Verified, and verifiable.** The server stores each episode's seed and action trace, and re-verifies every finished episode by replaying it: the replay must end on the same `state_hash`. Then the seed and the full tape are published, so anyone can replay it with jackdaw and check.

Your agent keeps running on your machine and plays over HTTPS. Observations and actions are exactly those of jackdaw's `BalatroGymnasiumEnv`, so a policy trained locally plugs in unchanged.

## Evaluate an agent

1. Sign in on the site with GitHub. Create an agent, then a token (it's shown once).
2. Install the client and make the token available as `ARENA_TOKEN`, or save it to `~/.jackdaw-arena/token`:

   ```bash
   uv add "jackdaw-arena @ git+https://github.com/TylerFlar/jackdaw-arena#subdirectory=client"
   ```

3. Play. `ArenaEnv` is a drop-in for `BalatroGymnasiumEnv` (same spaces, `action_masks()`, the same `balatro/*` info keys):

   ```python
   from jackdaw_arena import ArenaEnv

   env = ArenaEnv()
   obs, info = env.reset()           # the server picks the seed
   done = False
   while not done:
       action = model.predict(obs, action_masks=env.action_masks())[0]
       obs, reward, terminated, truncated, info = env.step(int(action))
       done = terminated or truncated
   print(info["balatro/rounds_beaten"], info["arena/seed"])   # revealed at the end
   ```

   Or spend a whole budget in batches with `evaluate()`. It takes the chooser signature of jackdaw's `examples/balatro_sb3.py` and never starts more episodes than you ask for. An interrupted run picks up where it stopped:

   ```python
   from sb3_contrib import MaskablePPO
   from jackdaw_arena import evaluate

   model = MaskablePPO.load("maskable_ppo_balatro.zip")

   def choose(envs, obs, masks):
       actions, _ = model.predict(obs, action_masks=masks, deterministic=True)
       return actions

   print(evaluate(choose, episodes=500, batch=32).summary())
   ```

4. Check any finished episode yourself (needs `jackdaw` installed):

   ```bash
   jackdaw-arena tape <episode-id> -o tape.json
   jackdaw-arena verify tape.json
   ```

The API is documented at [/api/docs](https://arena.tylerflar.com/api/docs). The agent protocol lives under `/api/v1`. Steps are batched (up to 256 per request). Every request is idempotent: resending a lost one returns the same result, and episode creation is keyed by your own UUIDs.

## Scoring

| | |
|---|---|
| Rank key | mean blinds beaten (rounds won), with its standard error and 95% interval |
| Also shown | win rate with a Wilson interval, mean and best ante, mean length, truncated and forfeited shares, a histogram of blinds beaten |
| Track `red-1` | Red Deck, white stake, 2,000-step cap, ends on a win: jackdaw's own evaluation protocol |
| Budget | 500 episodes per agent, track and engine version (season); ranked once all have ended |
| Limits | 5 agents per user, 64 running episodes per agent; an episode idle for 10 minutes is ended |
| Refused actions | an episode that ends because the engine refused an action scores 0, as in jackdaw's `run_episodes` |

An agent is a frozen policy: a new version is a new agent. The house baselines are listed apart. `random` picks uniformly among legal actions. `smart` is jackdaw's scripted agent, and it is privileged: it reads face-down cards.

## How it works

```
browser / agent ─HTTPS─▶ CloudFront (arena.tylerflar.com, ACM certificate, HSTS + CSP)
                           ├─ /                     ─▶ S3: the React app (private bucket, origin access control)
                           ├─ /api/* public reads   ─▶ Lambda function URL, cached at the edge for the API's s-maxage
                           └─ /api/v1, /api/me, /auth, /healthz ─▶ the same Lambda, never cached
Lambda "arena-api"   container image: FastAPI + jackdaw behind the Lambda Web Adapter; alias "live"
Lambda "arena-tasks" the same image: migrations, the idle janitor (EventBridge Scheduler), house runs
Aurora DSQL          serverless PostgreSQL (IAM auth): seeds, traces, results; backed up daily
```

- **Storage is tiny.** The engine is deterministic, so an episode is its seed plus one `uint16` per step. Any state can be rebuilt by replay.
- **The action index isn't a stable action id.** The server records each step's canonical engine action (the tape), and verifies the replay against a shadow game.
- **Scaling.** Lambda adds environments as traffic grows, DSQL scales by itself, and CloudFront serves the public pages. The limits are Terraform variables (`api_max_concurrency`, `api_memory_mb`). An idle site costs about $0.55 a month: the Route 53 zone, plus cents of storage. Under load, beyond the free tiers, it costs about $0.60 per million agent steps when they arrive in batches, as `evaluate()` sends them; sent one per request, closer to $2.
- **Security.**
  - API tokens and session ids are stored only as SHA-256 digests.
  - Sessions are server-side, in `__Host-` cookies. State-changing browser requests need a custom header and a matching Origin.
  - The Function URL refuses anything that didn't come through CloudFront.
  - The API connects to the database as a role that can't change the schema.
  - GitHub Actions deploys through OIDC, with no stored AWS keys.

## Repository

```
api/      the service (Python 3.13, FastAPI, SQLAlchemy Core, psycopg 3), its Dockerfile and tests
client/   the jackdaw-arena package: ArenaEnv, evaluate(), the CLI (no jackdaw dependency)
web/      the site (React 19, TypeScript, Vite, TanStack Query; types generated from the OpenAPI)
infra/    bootstrap/ (the state bucket) · terraform/ (everything else, with offline tests) · scripts/
.github/  CI, deploy and uptime workflows
```

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

The end-to-end test runs the production image behind Caddy, which stands in for CloudFront, with a mock OpenID provider standing in for GitHub:

```bash
(cd web && pnpm build)
docker compose --profile e2e up -d --build --wait
(cd web && pnpm e2e)
docker compose --profile e2e down -v
```

Infrastructure checks need no AWS account. The tests mock the provider:

```bash
cd infra/terraform
terraform init -backend=false && terraform validate && terraform test
tflint --init && tflint
```

## Running your own

Everything is in `infra/`. Terraform creates the resources; `infra/scripts/deploy.py` releases code into them. It's what the Deploy workflow runs on every green push to `main`.

1. **State bucket:** `terraform -chdir=infra/bootstrap init && terraform -chdir=infra/bootstrap apply`. Copy `infra/terraform/backend.hcl.example` to `backend.hcl`, then `terraform -chdir=infra/terraform init -backend-config=backend.hcl`.
2. **DNS:** copy `terraform.tfvars.example` to `terraform.tfvars` and run `terraform apply -target=aws_route53_zone.arena`. At your parent domain's DNS host, add the four `name_servers` as NS records for the subdomain.
3. **Sign-in:** create a GitHub OAuth App with the callback `https://<domain>/auth/callback/github`. Then run `infra/scripts/set-secrets.ps1` yourself: it stores the client ID and secret in SSM Parameter Store.
4. **First image, then everything:**
   - `terraform apply -target=aws_ecr_repository.api`
   - build and push `api/` for `linux/amd64`, tagged with the commit
   - set `api_image_uri`, then `terraform apply`

   CloudFront takes 5–15 minutes. If you set `alert_email`, confirm the two SNS emails.
5. **Release:** `uv run infra/scripts/deploy.py`. It migrates, publishes a version, health-checks it, moves the `live` alias, uploads the site and smoke-tests it, moving the alias back if anything fails. `--rollback` moves it back by hand.
6. **CI/CD:**
   - Set the `github_variables` output as repository variables.
   - Create a `production` environment limited to `main`.
   - The house baselines: `aws lambda invoke --function-name arena-tasks --payload '{"task":"house","agent":"smart","episodes":500}'`.

Function settings changed in Terraform (memory, environment) take effect at the next release, when a new version is published.

## License

MIT. Jackdaw Arena isn't affiliated with Balatro's developer or publisher. It ships no game art or other assets: the cards on the site are drawn with CSS.
