"""Small, owner/scope/query/version cache for derived indexes only.

Canonical SQL facts and mission receipts are always read again. The backend has
one writer process; every index mutation evicts that owner's entries. Restart
empties the cache, so an in-memory version cannot outlive a durable correction.
"""

import time
from collections import OrderedDict

_cache = OrderedDict()
_versions: dict[str, int] = {}


def invalidate(user_id: str):
    _versions[user_id] = _versions.get(user_id, 0) + 1
    for key in list(_cache):
        if key[0] == user_id:
            del _cache[key]
    if len(_versions) > 1024:
        _versions.clear()
        _cache.clear()


async def get_or_load(user_id: str, scope: str, query: str, source: str, loader):
    version = _versions.get(user_id, 0)
    key = (user_id, scope, " ".join(query.split()), version, source)
    old = _cache.get(key)
    if old and time.monotonic() - old[0] < 30:
        _cache.move_to_end(key)
        return [dict(item) for item in old[1]]
    result = await loader()
    # Do not cache outages/empty searches, or a result crossing an invalidation.
    if result and version == _versions.get(user_id, 0):
        _cache[key] = (time.monotonic(), [dict(item) for item in result])
        while len(_cache) > 256:
            _cache.popitem(last=False)
    return result
