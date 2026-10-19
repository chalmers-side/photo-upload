CREATE TABLE IF NOT EXISTS users (
  name TEXT PRIMARY KEY,
  password TEXT NOT NULL,
  is_root BOOLEAN NOT NULL DEFAULT FALSE,
  lang TEXT NOT NULL DEFAULT 'zh',
  created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  created_at DOUBLE PRECISION NOT NULL,
  slideshow_interval INTEGER NOT NULL,
  slideshow_queue_max INTEGER NOT NULL,
  slideshow_per_device INTEGER NOT NULL,
  slideshow_fade DOUBLE PRECISION NOT NULL,
  slideshow_mode TEXT NOT NULL,
  lottery_sphere_max INTEGER NOT NULL,
  lottery_seconds INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_projects (
  user_name TEXT NOT NULL REFERENCES users(name) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('admin', 'maintainer', 'guest')),
  PRIMARY KEY (user_name, project_id)
);

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  nickname TEXT NOT NULL DEFAULT '',
  lang TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS photos (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  caption TEXT NOT NULL DEFAULT '',
  device_id TEXT NOT NULL,
  ts DOUBLE PRECISION NOT NULL,
  person BOOLEAN,
  consent BOOLEAN,
  PRIMARY KEY (project_id, id)
);
ALTER TABLE photos ADD COLUMN IF NOT EXISTS consent BOOLEAN;
CREATE INDEX IF NOT EXISTS photos_project_ts ON photos (project_id, ts);
CREATE INDEX IF NOT EXISTS photos_device_ts ON photos (project_id, device_id, ts DESC);

CREATE TABLE IF NOT EXISTS tickets (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  serial TEXT NOT NULL,
  photo_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  ts DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (project_id, serial)
);
CREATE INDEX IF NOT EXISTS tickets_device ON tickets (project_id, device_id);

CREATE TABLE IF NOT EXISTS ticket_seq (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  n INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lottery_won (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  device_id TEXT NOT NULL,
  PRIMARY KEY (project_id, device_id)
);

CREATE TABLE IF NOT EXISTS kuji_config (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  per_user INTEGER NOT NULL,
  total_a INTEGER NOT NULL DEFAULT 0,
  total_b INTEGER NOT NULL DEFAULT 0,
  total_c INTEGER NOT NULL DEFAULT 0,
  total_d INTEGER NOT NULL DEFAULT 0,
  total_e INTEGER NOT NULL DEFAULT 0,
  label_a TEXT NOT NULL DEFAULT '',
  label_b TEXT NOT NULL DEFAULT '',
  label_c TEXT NOT NULL DEFAULT '',
  label_d TEXT NOT NULL DEFAULT '',
  label_e TEXT NOT NULL DEFAULT '',
  label_en_a TEXT NOT NULL DEFAULT '',
  label_en_b TEXT NOT NULL DEFAULT '',
  label_en_c TEXT NOT NULL DEFAULT '',
  label_en_d TEXT NOT NULL DEFAULT '',
  label_en_e TEXT NOT NULL DEFAULT '',
  seq INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kuji_draws (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  grade TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D', 'E')),
  device_id TEXT NOT NULL,
  ts DOUBLE PRECISION NOT NULL,
  claimed_at DOUBLE PRECISION,
  PRIMARY KEY (project_id, id)
);
CREATE INDEX IF NOT EXISTS kuji_draws_device ON kuji_draws (project_id, device_id);

CREATE TABLE IF NOT EXISTS challenge_sessions (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('demo', 'adventure')),
  status TEXT NOT NULL CHECK (status IN ('lobby', 'running', 'settling', 'done')),
  name TEXT NOT NULL DEFAULT '',
  pin TEXT NOT NULL DEFAULT '',
  started_at DOUBLE PRECISION,
  ends_at DOUBLE PRECISION,
  duration_seconds INTEGER NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (project_id, id)
);
CREATE INDEX IF NOT EXISTS challenge_sessions_live
  ON challenge_sessions (project_id, status);
ALTER TABLE challenge_sessions ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';
ALTER TABLE challenge_sessions ADD COLUMN IF NOT EXISTS pin TEXT NOT NULL DEFAULT '';
UPDATE challenge_sessions SET name = left(id, 12) WHERE name = '';
WITH numbered AS (
  SELECT project_id, id,
    lpad((row_number() OVER (PARTITION BY project_id ORDER BY created_at))::text, 4, '0') AS new_pin
  FROM challenge_sessions
  WHERE pin = '' AND status IN ('lobby', 'running')
)
UPDATE challenge_sessions s
SET pin = n.new_pin
FROM numbered n
WHERE s.project_id = n.project_id AND s.id = n.id;
CREATE UNIQUE INDEX IF NOT EXISTS challenge_sessions_name
  ON challenge_sessions (project_id, name);
CREATE UNIQUE INDEX IF NOT EXISTS challenge_sessions_live_pin
  ON challenge_sessions (project_id, pin) WHERE status IN ('lobby', 'running');

CREATE TABLE IF NOT EXISTS challenge_players (
  project_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  slot INTEGER NOT NULL,
  device_id TEXT NOT NULL,
  ready_at DOUBLE PRECISION,
  finished_at DOUBLE PRECISION,
  time_score INTEGER NOT NULL DEFAULT 0,
  task_score INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (project_id, session_id, device_id),
  UNIQUE (project_id, session_id, slot),
  FOREIGN KEY (project_id, session_id)
    REFERENCES challenge_sessions (project_id, id) ON DELETE CASCADE
);
ALTER TABLE challenge_players ADD COLUMN IF NOT EXISTS ready_at DOUBLE PRECISION;
ALTER TABLE challenge_players ADD COLUMN IF NOT EXISTS refresh_left INTEGER NOT NULL DEFAULT 0;
ALTER TABLE challenge_players ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '';
ALTER TABLE challenge_players ADD COLUMN IF NOT EXISTS avatar_id TEXT;

CREATE TABLE IF NOT EXISTS challenge_tasks (
  project_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  device_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  task_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('person', 'color', 'host', 'couple')),
  prompt_zh TEXT NOT NULL,
  prompt_en TEXT NOT NULL,
  points INTEGER NOT NULL,
  source_photo_id TEXT,
  color TEXT,
  status TEXT NOT NULL CHECK (
    status IN ('pending', 'judging', 'passed', 'failed', 'awaiting_host')
  ),
  photo_id TEXT,
  judge_score DOUBLE PRECISION,
  judge_detail TEXT,
  reviewed_by TEXT,
  PRIMARY KEY (project_id, session_id, device_id, idx),
  FOREIGN KEY (project_id, session_id, device_id)
    REFERENCES challenge_players (project_id, session_id, device_id)
    ON DELETE CASCADE
);
ALTER TABLE challenge_tasks ADD COLUMN IF NOT EXISTS pass_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE challenge_tasks ADD COLUMN IF NOT EXISTS band TEXT;
