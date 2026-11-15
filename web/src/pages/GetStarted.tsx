import { useEffect } from "react";
import { Link, useLocation } from "react-router";
import { useMe, useTracks } from "../api/hooks";

const INSTALL = `uv add "jackdaw-arena @ git+https://github.com/TylerFlar/jackdaw-arena@main#subdirectory=client"`;

const ENV = `from jackdaw_arena import ArenaEnv

env = ArenaEnv()                  # a drop-in for jackdaw's BalatroGymnasiumEnv
obs, info = env.reset()           # the server picks a fresh, secret seed
done = False
while not done:
    action = model.predict(obs, action_masks=env.action_masks())[0]
    obs, reward, terminated, truncated, info = env.step(int(action))
    done = terminated or truncated
print(info["balatro/rounds_beaten"], info["arena/seed"])   # the seed is revealed at the end`;

const EVALUATE = `from sb3_contrib import MaskablePPO
from jackdaw_arena import evaluate

model = MaskablePPO.load("maskable_ppo_balatro.zip")

def choose(envs, obs, masks):        # jackdaw's examples/balatro_sb3.py signature
    actions, _ = model.predict(obs, action_masks=masks, deterministic=True)
    return actions

result = evaluate(choose, episodes=500, batch=32)
print(result.summary())               # blinds beaten +- SEM, ante, win rate, length`;

export function GetStartedPage() {
  const { data: me } = useMe();
  const { data: tracks } = useTracks();
  const k = tracks?.[0]?.episodes_per_agent ?? 500;
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);
  return (
    <>
      <h1>Get started</h1>
      <p className="lede">
        Your agent runs on your machine. Every run it plays happens on the server, on a seed chosen
        there and kept secret until the run ends. The observations and actions are exactly those of
        jackdaw's <code>BalatroGymnasiumEnv</code>, so a policy trained locally plugs in unchanged.
      </p>

      <section className="panel">
        <h2>1. Create an agent and a token</h2>
        <p>
          {me ? (
            <>
              On <Link to="/me">your agents</Link> page, create an agent and mint a token for it.
            </>
          ) : (
            <>Sign in, then create an agent and mint a token for it on your account page.</>
          )}{" "}
          The token is shown once. Save it to <code>~/.jackdaw-arena/token</code> or export it as{" "}
          <code>ARENA_TOKEN</code>.
        </p>
      </section>

      <section className="panel">
        <h2>2. Install the client</h2>
        <pre>{INSTALL}</pre>
        <p className="muted small">Python 3.10+. It needs only httpx, numpy and gymnasium.</p>
      </section>

      <section className="panel">
        <h2>3. Play</h2>
        <pre>{ENV}</pre>
        <p>To evaluate a whole budget in batches, use <code>evaluate()</code>:</p>
        <pre>{EVALUATE}</pre>
        <p className="muted small">
          Or from a shell: <code>jackdaw-arena eval --episodes {k}</code> (a random policy), or{" "}
          <code>--policy mypackage.agent:make_chooser</code>.
        </p>
      </section>

      <section className="panel" id="scoring">
        <h2>How agents are scored</h2>
        <ul>
          <li>
            <strong>Score</strong> is the average number of blinds an agent beats per run: higher is
            better. Small and big blinds count as well as bosses, so clearing ante 1 is 3.
          </li>
          <li>
            The <strong>±</strong> after a score is its 95% margin of error: the agent's true average
            is very likely within that distance of its score. When two agents' ranges overlap, more
            runs could swap them.
          </li>
          <li>
            An agent ranks once all <strong>{k} runs</strong> on a track have ended. Until then it's
            listed under In progress.
          </li>
          <li>
            Every run counts. A run stopped early (a reset, closing the client, or 10 minutes idle)
            scores the blinds it beat before it stopped, so stopping never helps. A run the engine
            refuses, when an action the mask allowed turns out to be illegal, scores 0.
          </li>
          <li>
            The <strong>baselines</strong> show where simple play lands: <em>random</em> picks any legal
            action, and <em>smart</em> is jackdaw's hand-written agent. Smart reads face-down cards,
            so it isn't ranked.
          </li>
        </ul>
      </section>

      <section className="panel">
        <h2>The rules</h2>
        <ul>
          <li>Each agent plays {k} runs per track. A new version of a policy is a new agent.</li>
          <li>
            Seeds are 16 random characters, unique to each run and secret until it ends. Then the
            seed, the full action tape and the final state hash are public, and anyone can replay
            them with jackdaw.
          </li>
          <li>Every ended run is verified on the server by an independent replay of its tape.</li>
          <li>Unlisted agents stay off the leaderboard; their replays are visible only to you.</li>
        </ul>
      </section>

      <section className="panel">
        <h2>The protocol</h2>
        <p>
          The client is a thin layer over a small HTTP API: <code>POST /api/v1/episodes</code>,{" "}
          <code>POST /api/v1/step</code> (batched), <code>GET /api/v1/episodes/{"{id}"}</code> and{" "}
          <code>POST …/forfeit</code>. Every call is safe to retry. See the{" "}
          <a href="/api/docs">interactive API reference</a>.
        </p>
      </section>
    </>
  );
}
