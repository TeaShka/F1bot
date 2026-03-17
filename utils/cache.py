"""
Кэширование запросов к Jolpica API.
Результат хранится в памяти 1 час (3600 сек).
"""

import time
import logging
import aiohttp

logger = logging.getLogger(__name__)

# Словарь: url -> (timestamp, data)
_cache: dict[str, tuple[float, dict]] = {}

CACHE_TTL = 3600  # секунд


async def fetch_with_cache(url: str, ttl: int = CACHE_TTL) -> dict | None:
    """
    GET-запрос с кэшированием.
    Если данные в кэше свежие — возвращает их без запроса к API.
    """
    now = time.monotonic()

    if url in _cache:
        ts, data = _cache[url]
        if now - ts < ttl:
            logger.debug("Кэш HIT: %s", url)
            return data

    logger.debug("Кэш MISS: %s", url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    _cache[url] = (now, data)
                    return data
                logger.warning("API вернул %d для %s", resp.status, url)
                return None
    except Exception as exc:
        logger.error("Ошибка запроса %s: %s", url, exc)
        return None


def invalidate_cache(url: str) -> None:
    """Принудительно очищает кэш для конкретного URL."""
    _cache.pop(url, None)


def clear_all_cache() -> None:
    """Очищает весь кэш."""
    _cache.clear()
