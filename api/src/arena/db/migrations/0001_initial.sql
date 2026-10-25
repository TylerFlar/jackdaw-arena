-- The initial schema. Written for Aurora DSQL and plain PostgreSQL 16 alike:
-- no array columns, no SAVEPOINT, one statement per transaction (the runner executes each
-- statement on its own), and idempotent statements so a half-applied migration can rerun.
-- On DSQL the runner turns CREATE INDEX into CREATE INDEX ASYNC and waits for the jobs.

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    login text NOT NULL,
    name text,
    avatar_url text,
    is_admin boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL
);

-- One row per external account: GitHub's numeric id, or an OIDC issuer's subject.
CREATE TABLE IF NOT EXISTS identities (
    provider text NOT NULL,
    subject text NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (provider, subject)
);

-- Browser sessions. The cookie holds a random token; only its SHA-256 is stored.
CREATE TABLE IF NOT EXISTS sessions (
    id_hash text PRIMARY KEY,
    user_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    slug text NOT NULL UNIQUE,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    url text,
    kind text NOT NULL DEFAULT 'user',
    unlisted boolean NOT NULL DEFAULT false,
    hidden boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL
);

-- Agent API tokens ("jdk_..."). Only the SHA-256 is stored.
CREATE TABLE IF NOT EXISTS api_tokens (
    id uuid PRIMARY KEY,
    agent_id uuid NOT NULL,
    token_hash text NOT NULL UNIQUE,
    prefix text NOT NULL,
    label text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL,
    last_used_at timestamptz,
    revoked_at timestamptz
);

CREATE TABLE IF NOT EXISTS tracks (
    key text PRIMARY KEY,
    name text NOT NULL,
    back text NOT NULL,
    stake smallint NOT NULL,
    max_steps integer NOT NULL,
    end_on_win boolean NOT NULL,
    max_free_moves smallint,
    episodes_per_agent integer NOT NULL,
    active boolean NOT NULL DEFAULT true
);

-- Episodes an agent has started per track and season: the fixed evaluation budget.
CREATE TABLE IF NOT EXISTS quotas (
    agent_id uuid NOT NULL,
    track text NOT NULL,
    season text NOT NULL,
    used integer NOT NULL,
    PRIMARY KEY (agent_id, track, season)
);

-- An episode is its spec (enough to rebuild it exactly) plus the indices the agent chose
-- (trace: uint16 little-endian per step). The canonical tape and the outcome are written once,
-- when it ends.
CREATE TABLE IF NOT EXISTS episodes (
    id uuid PRIMARY KEY,
    agent_id uuid NOT NULL,
    track text NOT NULL,
    client_key uuid NOT NULL,
    season text NOT NULL,
    action_version smallint NOT NULL,
    seed text NOT NULL UNIQUE,
    rng_seed bigint NOT NULL,
    back text NOT NULL,
    stake smallint NOT NULL,
    max_steps integer NOT NULL,
    end_on_win boolean NOT NULL,
    max_free_moves smallint,
    reward_kind text NOT NULL,
    reward_weights jsonb,
    status text NOT NULL,
    t integer NOT NULL,
    trace bytea NOT NULL,
    created_at timestamptz NOT NULL,
    last_step_at timestamptz NOT NULL,
    ended_at timestamptz,
    end_reason text,
    won boolean,
    ante_reached smallint,
    rounds_beaten smallint,
    refused text,
    not_ported text,
    attempted jsonb,
    tape jsonb,
    final_state_hash text,
    verified boolean,
    engine_error text,
    UNIQUE (agent_id, client_key)
);

CREATE INDEX IF NOT EXISTS episodes_agent_status ON episodes (agent_id, status);
CREATE INDEX IF NOT EXISTS episodes_board ON episodes (track, season, agent_id);
CREATE INDEX IF NOT EXISTS episodes_idle ON episodes (status, last_step_at);
CREATE INDEX IF NOT EXISTS agents_user ON agents (user_id);
CREATE INDEX IF NOT EXISTS api_tokens_agent ON api_tokens (agent_id);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id);

INSERT INTO tracks (key, name, back, stake, max_steps, end_on_win, max_free_moves, episodes_per_agent)
VALUES ('red-1', 'Red Deck, White Stake', 'b_red', 1, 2000, true, 10, 500)
ON CONFLICT (key) DO NOTHING;
