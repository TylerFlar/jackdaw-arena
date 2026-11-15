-- jackdaw's player view (player_view=True): an observation without the card identities a player
-- hasn't seen. A track serves it or the default observation, and each episode records which,
-- since an episode is rebuilt from its own row. NULL, on rows from before this file, is the
-- default observation.
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS player_view boolean;
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS player_view boolean;

-- red-1's game with the player view: its own leaderboard and budget, so agents that see less
-- aren't ranked against agents that see more.
INSERT INTO tracks (key, name, back, stake, max_steps, end_on_win, max_free_moves, episodes_per_agent, player_view)
VALUES ('red-1-pv', 'Red Deck, White Stake, player view', 'b_red', 1, 2000, true, 10, 500, true)
ON CONFLICT (key) DO NOTHING;
