CREATE TABLE IF NOT EXISTS scores (
  day TEXT NOT NULL,
  uid TEXT NOT NULL,
  score INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (day, uid)
);
CREATE TABLE IF NOT EXISTS picks (
  day TEXT NOT NULL,
  uid TEXT NOT NULL,
  slot INTEGER NOT NULL,
  player INTEGER NOT NULL,
  PRIMARY KEY (day, uid, slot)
);
CREATE INDEX IF NOT EXISTS picks_day ON picks (day, slot, player);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER NOT NULL,
  day TEXT,
  sport TEXT,
  prompt TEXT,
  note TEXT NOT NULL
);
