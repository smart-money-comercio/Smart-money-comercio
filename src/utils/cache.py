from datetime import datetime, timedelta, timezone

CACHE = {}


def get_cache(key):
    item = CACHE.get(key)

    if not item:
        return None

    now = datetime.now(timezone.utc)

    if now > item["expires_at"]:
        del CACHE[key]
        return None

    return item["value"]


def set_cache(key, value, ttl_seconds=900):
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    CACHE[key] = {
        "value": value,
        "expires_at": expires_at,
    }


def clear_cache(prefix=None):
    if prefix is None:
        CACHE.clear()
        return

    keys_to_delete = [
        key for key in CACHE
        if key.startswith(prefix)
    ]

    for key in keys_to_delete:
        del CACHE[key]