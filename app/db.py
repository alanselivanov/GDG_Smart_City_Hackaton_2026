from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS pois (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  names_json TEXT NOT NULL,
  description TEXT,
  category TEXT NOT NULL,
  tags_json TEXT NOT NULL,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  opening_hours TEXT,
  website TEXT,
  phone TEXT,
  source_url TEXT NOT NULL,
  source_updated_at TEXT,
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pois_location ON pois(lat, lon);
CREATE INDEX IF NOT EXISTS idx_pois_category ON pois(category);
CREATE TABLE IF NOT EXISTS sync_state (
  source TEXT PRIMARY KEY,
  last_success_at TEXT NOT NULL,
  count INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    def upsert_pois(self, pois: list[dict]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            con.executemany(
                """INSERT INTO pois
                (id,name,names_json,description,category,tags_json,lat,lon,
                 opening_hours,website,phone,source_url,source_updated_at,fetched_at)
                VALUES (:id,:name,:names_json,:description,:category,:tags_json,:lat,:lon,
                        :opening_hours,:website,:phone,:source_url,:source_updated_at,:fetched_at)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,names_json=excluded.names_json,
                  description=excluded.description,category=excluded.category,
                  tags_json=excluded.tags_json,lat=excluded.lat,lon=excluded.lon,
                  opening_hours=excluded.opening_hours,website=excluded.website,
                  phone=excluded.phone,source_url=excluded.source_url,
                  source_updated_at=excluded.source_updated_at,fetched_at=excluded.fetched_at""",
                [{**poi, "fetched_at": now} for poi in pois],
            )
            con.execute("DELETE FROM pois WHERE fetched_at != ?", (now,))
            con.execute(
                """INSERT INTO sync_state(source,last_success_at,count) VALUES('openstreetmap',?,?)
                ON CONFLICT(source) DO UPDATE SET last_success_at=excluded.last_success_at,
                count=excluded.count""",
                (now, len(pois)),
            )
        return len(pois)

    def all_pois(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM pois").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["names"] = json.loads(item.pop("names_json"))
            item["tags"] = json.loads(item.pop("tags_json"))
            result.append(item)
        return result

    def status(self) -> dict:
        with self.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM pois").fetchone()[0]
            row = con.execute("SELECT last_success_at,count FROM sync_state WHERE source='openstreetmap'").fetchone()
        return {"poi_count": count, "last_success_at": row[0] if row else None, "last_fetch_count": row[1] if row else 0}
