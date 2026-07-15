from typing import Optional

from pydantic import BaseModel


class CrawlRequest(BaseModel):
    url: str
    threads: Optional[int] = 10
    delay: Optional[float] = 0.5
    timeout: Optional[int] = 10
    tor_proxy: Optional[str] = "socks5h://127.0.0.1:9050"
    max_depth: Optional[int] = 0
    scope: Optional[str] = None
    exclude: Optional[list[str]] = None
    content_types: Optional[str] = None
    domains_only: Optional[bool] = False
    respect_robots: Optional[bool] = True
    js_render: Optional[bool] = False
    dedup: Optional[bool] = False
    secrets: Optional[bool] = False
    harvest: Optional[bool] = False
    wayback: Optional[bool] = False
    adaptive_delay: Optional[bool] = False
    api_mode: Optional[bool] = False


class CrawlStatus(BaseModel):
    id: str
    url: str
    status: str
    pages_crawled: int
    domains_found: int
    errors: int
    start_time: str
    duration: str
