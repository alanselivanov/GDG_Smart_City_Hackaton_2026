"""Persistent OpenAI embeddings for source-backed POI retrieval."""
from __future__ import annotations

import asyncio
import hashlib
import math
import struct

import httpx

from app.config import Settings, settings
from app.db import Database
from app.recommend import CATEGORY_LABELS


class EmbeddingError(Exception):
    pass


def poi_text(poi: dict) -> str:
    tags = poi["tags"]
    parts = ["Astana place", *dict.fromkeys(poi["names"].values()),
             *(CATEGORY_LABELS[language][poi["category"]] for language in ("ru", "kk", "en"))]
    parts.extend(str(tags[key]) for key in (
        "cuisine", "tourism", "amenity", "leisure", "historic", "shop", "interactive",
        "description", "description:ru", "description:kk", "description:en", "2gis:rubrics"
    ) if tags.get(key))
    return " | ".join(parts)[:1800]


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pack(vector: list[float], dimensions: int) -> bytes:
    if len(vector) != dimensions or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
        raise EmbeddingError("Embedding API returned an invalid vector")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm < 1e-10:
        raise EmbeddingError("Embedding API returned a zero vector")
    return struct.pack("<" + "f" * dimensions, *(x / norm for x in vector))


def _unpack(value: bytes, dimensions: int) -> tuple[float, ...]:
    if len(value) != dimensions * 4:
        raise EmbeddingError("Stored embedding has an invalid dimension")
    return struct.unpack("<" + "f" * dimensions, value)


async def embed_texts(texts: list[str], config: Settings = settings) -> list[bytes]:
    if not config.llm_api_key:
        raise EmbeddingError("LLM_API_KEY is required for semantic retrieval")
    payload = {"model": config.embedding_model, "dimensions": config.embedding_dimensions,
               "encoding_format": "float", "input": texts}
    try:
        async with httpx.AsyncClient(timeout=config.llm_timeout_seconds) as client:
            for attempt in range(3):
                response = await client.post(config.llm_base_url.rstrip("/") + "/embeddings",
                                             headers={"Authorization": f"Bearer {config.llm_api_key}"}, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                result = response.json()
                break
        data = result["data"]
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingError("Embedding API returned an incomplete batch")
        by_index = {item["index"]: item["embedding"] for item in data}
        if set(by_index) != set(range(len(texts))):
            raise EmbeddingError("Embedding API returned invalid indexes")
        return [_pack(by_index[index], config.embedding_dimensions) for index in range(len(texts))]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise EmbeddingError(f"Embedding API failed: {type(exc).__name__}") from exc


async def ensure_index(db: Database, pois: list[dict], config: Settings = settings) -> int:
    existing = db.embeddings(config.embedding_model)
    missing = [(poi["id"], poi_text(poi)) for poi in pois
               if poi["id"] not in existing or existing[poi["id"]][0] != content_hash(poi_text(poi))
               or len(existing[poi["id"]][1]) != config.embedding_dimensions * 4]
    for start in range(0, len(missing), 64):
        batch = missing[start:start + 64]
        vectors = await embed_texts([text for _, text in batch], config)
        db.save_embeddings([(poi_id, config.embedding_model, content_hash(text), vector)
                            for (poi_id, text), vector in zip(batch, vectors)])
        if start + 64 < len(missing):
            await asyncio.sleep(0.15)
    return len(missing)


async def semantic_scores(db: Database, pois: list[dict], query: str,
                          config: Settings = settings) -> dict[str, float]:
    stored_pois = [poi for poi in pois if not poi["id"].startswith("2gis/")]
    external_pois = [poi for poi in pois if poi["id"].startswith("2gis/")]
    await ensure_index(db, stored_pois, config)
    query_vector = _unpack((await embed_texts([query], config))[0], config.embedding_dimensions)
    stored = db.embeddings(config.embedding_model)
    scores = {}
    for poi in stored_pois:
        row = stored.get(poi["id"])
        if row is None or row[0] != content_hash(poi_text(poi)):
            raise EmbeddingError("Semantic index is incomplete")
        vector = _unpack(row[1], config.embedding_dimensions)
        scores[poi["id"]] = sum(a * b for a, b in zip(query_vector, vector))
    # Catalog results are request-scoped and must not enter the OSM cache/FK table.
    for start in range(0, len(external_pois), 64):
        batch = external_pois[start:start + 64]
        vectors = await embed_texts([poi_text(poi) for poi in batch], config)
        for poi, packed in zip(batch, vectors):
            vector = _unpack(packed, config.embedding_dimensions)
            scores[poi["id"]] = sum(a * b for a, b in zip(query_vector, vector))
    return scores


async def main() -> None:
    db = Database(settings.database_path)
    db.init()
    pois = db.all_pois()
    if not pois:
        raise SystemExit("No POI data; run python -m app.ingest first")
    count = await ensure_index(db, pois)
    print(f"Indexed {count} changed POI; {len(pois)} total")


if __name__ == "__main__":
    asyncio.run(main())
