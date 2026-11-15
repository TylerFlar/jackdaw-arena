-- jackdaw 0.3.0 has one observation, the player's view, so every track serves it and red-1-pv
-- (0003: red-1's game with that view) is red-1 again: it retires. A retired track is listed
-- nowhere and takes no new episodes; its ended episodes stay public and verifiable. The
-- player_view columns stay as they are, unread, since migrations only expand.
UPDATE tracks SET active = false WHERE key = 'red-1-pv';
