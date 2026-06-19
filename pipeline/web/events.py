"""대시보드 실시간 이벤트 브로드캐스트."""

from __future__ import annotations

import queue
import threading

_bus: EventBus | None = None


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[queue.Queue[bool]] = []

    def subscribe(self) -> queue.Queue[bool]:
        q: queue.Queue[bool] = queue.Queue(maxsize=16)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[bool]) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self) -> None:
        with self._lock:
            for sub in self._subs:
                try:
                    sub.put_nowait(True)
                except queue.Full:
                    try:
                        sub.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        sub.put_nowait(True)
                    except queue.Full:
                        pass


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def notify_dashboard() -> None:
    get_event_bus().publish()
