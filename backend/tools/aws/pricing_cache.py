"""
Pricing cache — live AWS Pricing API responses cached in SQLite with TTL.

Usage:
    from tools.aws.pricing_cache import get_cached_or_fetch

    price = await get_cached_or_fetch(
        service_key="ec2.t3.micro",
        region="eu-west-3",
        fetcher=fetch_ec2_price_live,
        params={"instance_type": "t3.micro", "region": "eu-west-3"},
    )

Cache hit: <1ms. Cache miss: 3-8s (live API call), then cached for 7 days.
"""
from __future__ import annotations
import asyncio
import functools
import json
import os
import sqlite3
import time
from typing import Any, Callable, Optional

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
CACHE_DB_PATH = os.environ.get(
    "PRICING_CACHE_DB",
    os.path.join(os.path.dirname(__file__), "..", "..", "pricing_cache.db"),
)


def _init_db():
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pricing_cache (
            cache_key   TEXT PRIMARY KEY,
            value_usd   REAL NOT NULL,
            metadata    TEXT,
            source      TEXT NOT NULL,
            cached_at   INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_at ON pricing_cache(cached_at)")
    conn.commit()
    conn.close()


_init_db()


def _cache_key(service_key: str, region: str, params: dict) -> str:
    """Stable hash-like key from service + region + sorted params."""
    params_str = json.dumps(params, sort_keys=True)
    return f"{service_key}::{region}::{params_str}"


def _get_from_cache(key: str) -> Optional[dict]:
    conn = sqlite3.connect(CACHE_DB_PATH)
    try:
        row = conn.execute(
            "SELECT value_usd, metadata, source, cached_at FROM pricing_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        value_usd, metadata_json, source, cached_at = row
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            return None  # expired
        return {
            "value_usd": value_usd,
            "metadata":  json.loads(metadata_json or "{}"),
            "source":    source,
            "cached_at": cached_at,
            "cache_hit": True,
        }
    finally:
        conn.close()


def _set_cache(key: str, value_usd: float, source: str, metadata: dict):
    conn = sqlite3.connect(CACHE_DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO pricing_cache (cache_key, value_usd, metadata, source, cached_at) VALUES (?, ?, ?, ?, ?)",
            (key, value_usd, json.dumps(metadata), source, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


async def get_cached_or_fetch(
    service_key: str,
    region: str,
    fetcher: Callable[..., dict],
    params: dict,
    fallback_usd: float = 0.0,
) -> dict:
    """
    Try cache → live API → fallback (in that order).

    fetcher: async function returning {"value_usd": float, "metadata": dict}
             on success, or raising on failure.
    fallback_usd: hardcoded value used if both cache and API fail.
    """
    key = _cache_key(service_key, region, params)

    # Cache lookup
    cached = _get_from_cache(key)
    if cached:
        return cached

    # Live fetch
    try:
        result = await fetcher(**params)
        if isinstance(result, dict) and "value_usd" in result and result["value_usd"] > 0:
            _set_cache(key, result["value_usd"], "live_api", result.get("metadata", {}))
            return {
                "value_usd":  result["value_usd"],
                "metadata":   result.get("metadata", {}),
                "source":     "live_api",
                "cached_at":  int(time.time()),
                "cache_hit":  False,
            }
    except Exception as e:
        # Live API failed — fall through to hardcoded fallback
        pass

    # Hardcoded fallback (no caching of fallback values — they may be off)
    return {
        "value_usd":  fallback_usd,
        "metadata":   {"note": "Reference pricing (cache miss + live API unavailable)"},
        "source":     "reference",
        "cached_at":  None,
        "cache_hit":  False,
    }


def clear_cache():
    """Clear the entire pricing cache."""
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute("DELETE FROM pricing_cache")
    conn.commit()
    conn.close()


def cache_stats() -> dict:
    conn = sqlite3.connect(CACHE_DB_PATH)
    try:
        total = conn.execute("SELECT COUNT(*) FROM pricing_cache").fetchone()[0]
        fresh = conn.execute(
            "SELECT COUNT(*) FROM pricing_cache WHERE cached_at > ?",
            (int(time.time() - CACHE_TTL_SECONDS),),
        ).fetchone()[0]
        by_source = dict(conn.execute(
            "SELECT source, COUNT(*) FROM pricing_cache GROUP BY source"
        ).fetchall())
        return {
            "total_entries":  total,
            "fresh_entries":  fresh,
            "expired":        total - fresh,
            "by_source":      by_source,
            "db_path":        CACHE_DB_PATH,
            "ttl_days":       CACHE_TTL_SECONDS / 86400,
        }
    finally:
        conn.close()
