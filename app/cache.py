import time


class TTLCache:
    """Простой in-memory кэш с временем жизни. В проде заменить на Redis."""

    def __init__(self, ttl: float = 24 * 3600):
        self.ttl = ttl
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if time.time() > expires:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value) -> None:
        self._data[key] = (time.time() + self.ttl, value)
