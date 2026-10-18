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
  PRIMARY KEY (project_id, id)
);
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
