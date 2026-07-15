import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CrawlerConfig:
    seed_url: str
    threads: int = 10
    delay: float = 0.5
    timeout: int = 10
    tor_proxy: str = "socks5h://127.0.0.1:9050"
    output_file: Optional[str] = None
    output_format: str = "txt"
    max_depth: int = 0
    verbose: bool = False
    report_file: Optional[str] = None
    domains_only: bool = False
    auto_threads: bool = False
    respect_robots: bool = True
    resume_checkpoint: Optional[str] = None
    db_path: Optional[str] = None
    scope: Optional[str] = None
    exclude_patterns: list[str] = field(default_factory=list)
    content_types: Optional[str] = None
    log_file: Optional[str] = None
    js_render: bool = False
    checkpoint_interval: int = 500
    proxy_file: Optional[str] = None
    proxy_api: Optional[str] = None
    dedup: bool = False
    graph_file: Optional[str] = None
    graph_format: str = "json"
    secrets: bool = False
    harvest: bool = False
    wayback: bool = False
    adaptive_delay: bool = False
    plugin_dir: Optional[str] = None
    broken_links_only: bool = False
    api_mode: bool = False
    redis_url: Optional[str] = None

    # Phase 2 — Crawl strategy
    crawl_strategy: str = "bfs"
    normalize_urls: bool = True
    strip_www: bool = True
    sort_query_params: bool = True

    # Phase 2 — Crawl budget
    max_pages_per_domain: int = 0
    max_time_per_domain: int = 0
    max_size_per_domain: int = 0

    # Phase 2 — New features
    tech_fingerprint: bool = False
    extract_content: bool = False
    seo_analysis: bool = False

    def __post_init__(self):
        self._exclude_compiled = [re.compile(p) for p in self.exclude_patterns]
        self._allowed_ct = [ct.strip() for ct in (self.content_types or "").split(",")] if self.content_types else []

    @property
    def exclude_compiled(self) -> list[re.Pattern]:
        return self._exclude_compiled

    @property
    def allowed_content_type_list(self) -> list[str]:
        return self._allowed_ct
