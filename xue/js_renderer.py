import threading

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class JsRenderer:
    def __init__(self, threads: int = 5):
        self._playwright = None
        self._browser = None
        self._contexts = []
        self._context_idx = 0
        self._lock = threading.Lock()

    def start(self, threads: int) -> None:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("playwright is not installed")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        for _ in range(min(threads, 8)):
            self._contexts.append(self._browser.new_context())

    def _get_context(self):
        with self._lock:
            ctx = self._contexts[self._context_idx % len(self._contexts)]
            self._context_idx += 1
            return ctx

    def render(self, url: str, timeout: int = 10) -> tuple[str, int, str]:
        if not self._contexts:
            return None, None, None
        try:
            ctx = self._get_context()
            page = ctx.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            html = page.content()
            page.close()
            return html, 200, "text/html"
        except Exception:
            return None, None, None

    def stop(self) -> None:
        for ctx in self._contexts:
            try:
                ctx.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
