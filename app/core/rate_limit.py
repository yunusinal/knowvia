"""Kayan pencereli (sliding window) istek sınırı; herkese açık demoda kota ve parola denemelerini korur.

Sayaçlar bellektedir: uygulama tek süreçte çalıştığı için (Qdrant local kilidi) yeterlidir; yeniden
başlatınca sıfırlanır. Tarayıcılar API'ye Streamlit sunucusu üzerinden geldiği için API istemci IP'sini
görmez; bu yüzden anahtarlar IP değil kullanıcı, e-posta ve genel toplam üzerinedir.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int | None:
        """İsteği sayar. Sınır aşıldıysa sayılmaz ve kaç saniye sonra denenebileceği döner; aşılmadıysa None."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, math.ceil(self._window - (now - hits[0])))
            hits.append(now)
            if len(self._hits) > 10_000:
                self._forget_idle(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _forget_idle(self, now: float) -> None:
        # Çok sayıda farklı anahtarla belleğin şişmesini önler (ör. rastgele e-postalarla giriş denemesi).
        for key in [key for key, hits in self._hits.items() if not hits or now - hits[-1] >= self._window]:
            del self._hits[key]
