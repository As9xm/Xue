import collections
import threading


class AdaptiveDelay:
    def __init__(self, base_delay=0.5, min_delay=0.1, max_delay=10.0, error_threshold=0.15):
        self.base_delay = base_delay
        self.current_delay = base_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.error_threshold = error_threshold
        self._recent_results = collections.deque(maxlen=100)
        self._lock = threading.Lock()

    def record_result(self, status_code):
        with self._lock:
            is_error = status_code >= 400
            self._recent_results.append(is_error)
            error_rate = sum(self._recent_results) / len(self._recent_results)
            if error_rate > self.error_threshold:
                self.current_delay = min(self.current_delay * 1.5, self.max_delay)
            elif error_rate < self.error_threshold * 0.5 and self.current_delay > self.base_delay:
                self.current_delay = max(self.current_delay * 0.8, self.base_delay)

    def get_delay(self):
        with self._lock:
            return self.current_delay

    def get_status(self):
        with self._lock:
            error_rate = sum(self._recent_results) / len(self._recent_results) if self._recent_results else 0
            return {
                "current_delay": round(self.current_delay, 2),
                "error_rate": round(error_rate, 3),
                "samples": len(self._recent_results),
            }
