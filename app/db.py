from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.attraction_facts import ATTRACTIONS, NUR_ALEM_FACT, VERIFIED_AT, name_matched_facts


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
CREATE TABLE IF NOT EXISTS poi_embeddings (
  poi_id TEXT PRIMARY KEY REFERENCES pois(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  vector BLOB NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocode_cache (
  query_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  source_url TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geocode_rate (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  next_allowed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS route_references (
  key TEXT PRIMARY KEY,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  source_url TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS poi_facts (
  poi_id TEXT NOT NULL REFERENCES pois(id) ON DELETE CASCADE,
  fact_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  text_ru TEXT NOT NULL,
  text_en TEXT NOT NULL,
  text_kk TEXT NOT NULL,
  action_ru TEXT NOT NULL,
  action_en TEXT NOT NULL,
  action_kk TEXT NOT NULL,
  source_url TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  PRIMARY KEY (poi_id, fact_key)
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
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)
            self._sync_attraction_facts(con)

    @staticmethod
    def _sync_attraction_facts(con: sqlite3.Connection) -> None:
        """Attach reviewed facts only when the current OSM object still matches."""
        rows = con.execute("SELECT id,name,lat,lon FROM pois").fetchall()
        matched = {row["id"] for row in rows if row["id"] in ATTRACTIONS and
                   ATTRACTIONS[row["id"]]["name_contains"].casefold() in row["name"].casefold()}
        dynamic = [(row["id"], fact) for row in rows
                   for fact in name_matched_facts(row["name"], row["lat"], row["lon"])]
        selected = [(poi_id, fact) for poi_id in matched for fact in ATTRACTIONS[poi_id]["facts"]]
        selected.extend(dynamic)
        source_urls = {fact["source_url"] for entry in ATTRACTIONS.values()
                       for fact in entry["facts"]} | {NUR_ALEM_FACT["source_url"]}
        con.execute("DELETE FROM poi_facts WHERE source_url IN ({})".format(
            ",".join("?" for _ in source_urls)), tuple(sorted(source_urls)))
        con.executemany(
            """INSERT INTO poi_facts
            (poi_id,fact_key,kind,text_ru,text_en,text_kk,action_ru,action_en,action_kk,source_url,verified_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [(poi_id, fact["key"], fact["kind"], fact["ru"], fact["en"], fact["kk"],
              fact["action_ru"], fact["action_en"], fact["action_kk"], fact["source_url"], VERIFIED_AT)
             for poi_id, fact in selected],
        )

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
            con.execute("DELETE FROM poi_embeddings WHERE poi_id NOT IN (SELECT id FROM pois)")
            self._sync_attraction_facts(con)
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
            fact_rows = con.execute("SELECT * FROM poi_facts ORDER BY poi_id,fact_key").fetchall()
        by_poi: dict[str, list[dict]] = {}
        for fact in fact_rows:
            by_poi.setdefault(fact["poi_id"], []).append(dict(fact))
        result = []
        for row in rows:
            item = dict(row)
            item["names"] = json.loads(item.pop("names_json"))
            item["tags"] = json.loads(item.pop("tags_json"))
            item["facts"] = by_poi.get(item["id"], [])
            result.append(item)
        return result

    def embeddings(self, model: str) -> dict[str, tuple[str, bytes]]:
        with self.connect() as con:
            rows = con.execute("SELECT poi_id,content_hash,vector FROM poi_embeddings WHERE model=?", (model,)).fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}

    def cached_geocode(self, key: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT name,lat,lon,source_url,fetched_at FROM geocode_cache WHERE query_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def route_reference(self, key: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT lat,lon,source_url,fetched_at FROM route_references WHERE key=?",
                              (key,)).fetchone()
        return dict(row) if row else None

    def save_route_reference(self, key: str, reference: dict) -> None:
        with self.connect() as con:
            con.execute("""INSERT INTO route_references(key,lat,lon,source_url,fetched_at)
                VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                lat=excluded.lat,lon=excluded.lon,source_url=excluded.source_url,
                fetched_at=excluded.fetched_at""",
                (key, reference["lat"], reference["lon"], reference["source_url"],
                 datetime.now(timezone.utc).isoformat()))

    def save_geocode(self, key: str, place: dict) -> None:
        with self.connect() as con:
            con.execute("""INSERT INTO geocode_cache(query_key,name,lat,lon,source_url,fetched_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(query_key) DO UPDATE SET name=excluded.name,
                lat=excluded.lat,lon=excluded.lon,source_url=excluded.source_url,fetched_at=excluded.fetched_at""",
                (key, place["name"], place["lat"], place["lon"], place["source_url"],
                 datetime.now(timezone.utc).isoformat()))

    def reserve_geocode_slot(self) -> float:
        import time
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT next_allowed_at FROM geocode_rate WHERE id=1").fetchone()
            now = time.time()
            start = max(now, row[0] if row else now)
            con.execute("""INSERT INTO geocode_rate(id,next_allowed_at) VALUES(1,?)
                ON CONFLICT(id) DO UPDATE SET next_allowed_at=excluded.next_allowed_at""", (start + 1.1,))
        return max(0.0, start - now)

    def save_embeddings(self, rows: list[tuple[str, str, str, bytes]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            con.executemany("""INSERT INTO poi_embeddings(poi_id,model,content_hash,vector,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(poi_id) DO UPDATE SET model=excluded.model,
                content_hash=excluded.content_hash,vector=excluded.vector,updated_at=excluded.updated_at""",
                [(poi_id, model, content_hash, vector, now) for poi_id, model, content_hash, vector in rows])

    def status(self) -> dict:
        with self.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM pois").fetchone()[0]
            row = con.execute("SELECT last_success_at,count FROM sync_state WHERE source='openstreetmap'").fetchone()
            embedding_count = con.execute("SELECT COUNT(*) FROM poi_embeddings").fetchone()[0]
        return {"poi_count": count, "embedding_count": embedding_count,
                "last_success_at": row[0] if row else None, "last_fetch_count": row[1] if row else 0}
