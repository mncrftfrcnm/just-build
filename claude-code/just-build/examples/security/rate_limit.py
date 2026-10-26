"""Optional illustrative local rate-limit primitive, NOT production distributed enforcement.

Adapt to the chosen web framework and trusted client identity. Use centralized atomic storage
when deployed across multiple workers/hosts. This file is a recipe, not auto-installed code.
"""
from collections import deque
from threading import Lock
import time


class WindowLimiter:
    def __init__(self, limit=30, window_seconds=60, clock=time.monotonic, max_identities=10000):
        if not isinstance(limit, int) or limit <= 0 or window_seconds <= 0 or not isinstance(max_identities, int) or max_identities <= 0:
            raise ValueError('positive limit and window required')
        self.limit, self.window, self.clock = limit, window_seconds, clock
        self.max_identities = max_identities
        self._lock, self._events = Lock(), {}

    def allow(self, identity):
        if not isinstance(identity, str) or not identity or len(identity) > 256:
            raise ValueError('use a bounded trusted identity; do not blindly trust client headers')
        now = self.clock()
        with self._lock:
            if identity not in self._events and len(self._events) >= self.max_identities:
                for key, events in list(self._events.items()):
                    while events and events[0] <= now - self.window:
                        events.popleft()
                    if not events:
                        del self._events[key]
                if len(self._events) >= self.max_identities:
                    return False, max(1, int(self.window))  # capacity safe-fail; tune for real deployments
            history = self._events.setdefault(identity, deque())
            while history and history[0] <= now - self.window:
                history.popleft()
            if len(history) >= self.limit:
                return False, max(1, int(history[0] + self.window - now + 0.9999))  # Retry-After seconds
            history.append(now)
            return True, 0
