"""
Shared HTTP client with TTL cache, request coalescing and stale fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CacheEntry:
    timestamp: float
    data: dict


class ApiClient:
    def __init__(self, timeout_seconds: int = 10, cache_dir: str = ".api_cache") -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, CacheEntry] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._cache_dir = Path(cache_dir)

    async def open(self) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def fetch_json(
        self,
        url: str,
        *,
        ttl: int = 0,
        allow_stale: bool = True,
    ) -> dict | None:
        now = time.time()
        cached = self._get_cached_entry(url)
        if ttl > 0 and cached and now - cached.timestamp < ttl:
            logger.debug("API cache hit: %s", url)
            return cached.data

        creator = False
        async with self._lock:
            now = time.time()
            cached = self._get_cached_entry(url)
            if ttl > 0 and cached and now - cached.timestamp < ttl:
                logger.debug("API cache hit after lock: %s", url)
                return cached.data

            task = self._inflight.get(url)
            if task is None:
                creator = True
                task = asyncio.create_task(self._fetch_and_store(url))
                self._inflight[url] = task

        try:
            data = await task
            if data is not None:
                return data
        finally:
            if creator:
                async with self._lock:
                    if self._inflight.get(url) is task:
                        self._inflight.pop(url, None)

        if allow_stale and cached:
            logger.warning("Using stale API cache for %s", url)
            return cached.data
        return None

    def invalidate(self, url: str) -> None:
        self._cache.pop(url, None)
        try:
            self._cache_path(url).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove API cache file for %s: %s", url, exc)

    def clear(self) -> None:
        self._cache.clear()
        if not self._cache_dir.exists():
            return
        for path in self._cache_dir.glob("*.json"):
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Failed to clear API cache file %s: %s", path, exc)

    async def _fetch_and_store(self, url: str) -> dict | None:
        await self.open()
        assert self._session is not None

        try:
            async with self._session.get(url) as response:
                if response.status != 200:
                    logger.warning("API returned %s for %s", response.status, url)
                    return None

                data = await response.json()
                entry = CacheEntry(time.time(), data)
                self._cache[url] = entry
                self._store_disk_cache(url, entry)
                return data
        except asyncio.TimeoutError:
            logger.error("API timeout for %s", url)
            return None
        except Exception as exc:
            logger.error("API request failed for %s: %s", url, exc)
            return None

    def _cache_path(self, url: str) -> Path:
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{cache_key}.json"

    def _get_cached_entry(self, url: str) -> CacheEntry | None:
        cached = self._cache.get(url)
        if cached is not None:
            return cached

        cached = self._load_disk_cache(url)
        if cached is not None:
            self._cache[url] = cached
        return cached

    def _load_disk_cache(self, url: str) -> CacheEntry | None:
        path = self._cache_path(url)
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            timestamp = float(payload["timestamp"])
            data = payload["data"]
            if not isinstance(data, dict):
                return None
            return CacheEntry(timestamp=timestamp, data=data)
        except Exception as exc:
            logger.warning("Failed to read API cache file %s: %s", path, exc)
            return None

    def _store_disk_cache(self, url: str, entry: CacheEntry) -> None:
        path = self._cache_path(url)
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "timestamp": entry.timestamp,
            "data": entry.data,
        }
        try:
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        except OSError as exc:
            logger.warning("Failed to write API cache file %s: %s", path, exc)
