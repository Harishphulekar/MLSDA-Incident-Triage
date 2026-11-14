"""Per-Client Sliding Window Rate Limiter."""
import time
from typing import Dict, List, Tuple
from src.agentops.logging import app_logger

class RateLimiter:
    """Sliding-window per-client rate limiter."""
    def __init__(self, requests_per_minute: int = 60, burst_limit: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.window_seconds = 60
        self._client_history: Dict[str, List[float]] = {}

    def is_allowed(self, client_id: str) -> Tuple[bool, int, int]:
        """
        Evaluates whether request from client_id is permitted.
        Returns: (allowed: bool, remaining_requests: int, retry_after_seconds: int)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Prune old timestamps
        history = self._client_history.setdefault(client_id, [])
        history = [ts for ts in history if ts > window_start]
        self._client_history[client_id] = history

        max_allowed = self.requests_per_minute + self.burst_limit
        current_count = len(history)

        if current_count >= max_allowed:
            oldest_ts = history[0]
            retry_after = int(max(1, (oldest_ts + self.window_seconds) - now))
            app_logger.warning(
                f"Rate limit exceeded for client '{client_id}': {current_count}/{max_allowed} requests",
                extra={"client_id": client_id, "retry_after": retry_after}
            )
            return False, 0, retry_after

        # Record this request
        history.append(now)
        remaining = max_allowed - len(history)
        return True, remaining, 0

    def reset(self):
        self._client_history.clear()

rate_limiter = RateLimiter()
