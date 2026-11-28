-- What a release needs to know before it continues a running episode another release served:
-- the jackdaw release that took its last step (or started it), and a digest of what its agent
-- saw then, the observation and the action each index of the table named. A release that
-- rebuilds the episode to another digest would read the agent's next index as another action,
-- so it voids the episode instead. NULL, on rows from before this file: the release is the
-- episode's engine_version, and there is no digest to check.
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS last_engine_version text;
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS state_digest text;
