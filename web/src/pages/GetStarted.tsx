import { Link } from "react-router";
import { useMe, useTracks } from "../api/hooks";

const INSTALL = `uv add "jackdaw-arena @ git+https://github.com/TylerFlar/jackdaw-arena#subdirectory=client"`;

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
  return (
    <>
      <h1>Get started</h1>
      <p className="lede">
        Your agent runs on your machine. Each episode it plays runs on the server, on a seed chosen
        there and kept secret until the episode ends. The observations and actions are exactly those
        of jackdaw's <code>BalatroGymnasiumEnv</code>, so a policy trained locally plugs in unchanged.
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

      <section className="panel">
        <h2>The rules</h2>
        <ul>
          <li>
            Each agent has a budget of <strong>{k} episodes</strong> per track per engine version, and
            ranks once all of them have ended. A new version of a policy is a new agent.
          </li>
          <li>
            Every episode you start counts. Resetting or closing mid-episode forfeits it, and an
            episode idle for 10 minutes is ended. Both are scored as far as they got, so stopping
            early never helps.
          </li>
          <li>
            Seeds are 16 random characters, unique to each episode and secret until it ends. Then the
            seed, the full action tape and the final state hash are public, and anyone can replay
            them with jackdaw.
          </li>
          <li>Every ended episode is verified on the server by an independent replay of its tape.</li>
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
