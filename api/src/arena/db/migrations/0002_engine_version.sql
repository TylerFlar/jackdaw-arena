-- The jackdaw release that recorded each episode. A season spans the releases that play the
-- same game; rows from before this column were recorded with their season's first release.
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS engine_version text;
