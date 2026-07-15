import re
from dataclasses import dataclass, field

SIGNATURES: list[tuple[str, list[re.Pattern], list[str]]] = [
    ("WordPress", [re.compile(r'<meta name="generator" content="WordPress', re.I)], ["/wp-content/", "/wp-includes/"]),
    ("Drupal", [re.compile(r'<meta name="Generator" content="Drupal', re.I), re.compile(r'Drupal\.settings', re.I)], ["/sites/default/", "/core/"]),
    ("Joomla", [re.compile(r'<meta name="generator" content="Joomla', re.I)], ["/components/com_", "/modules/mod_"]),
    ("Laravel", [], ["/vendor/laravel/"]),
    ("Django", [re.compile(r'csrfmiddlewaretoken', re.I)], ["/static/admin/", "/django/"]),
    ("React", [re.compile(r'data-reactroot', re.I), re.compile(r'data-reactid', re.I), re.compile(r'_reactListening', re.I)], []),
    ("Angular", [re.compile(r'ng-version=', re.I), re.compile(r'ng-app', re.I)], []),
    ("Vue.js", [re.compile(r'data-v-[a-f0-9]{8}', re.I), re.compile(r'__vue__', re.I)], []),
    ("Next.js", [re.compile(r'__NEXT_DATA__', re.I), re.compile(r'/next/static/', re.I)], ["/_next/"]),
    ("Nuxt.js", [re.compile(r'__NUXT__', re.I)], []),
    ("Gatsby", [re.compile(r'___gatsby', re.I)], []),
    ("Shopify", [re.compile(r'Shopify\.shop', re.I)], ["/cdn/shop/", "myshopify.com"]),
    ("Wix", [re.compile(r'Wix\.render', re.I)], ["/wix-thunderbolt/"]),
    ("Squarespace", [re.compile(r'squarespace\.com', re.I)], ["/squarespace/"]),
    ("Bootstrap", [re.compile(r'bootstrap\.min\.css', re.I), re.compile(r'bootstrap\.bundle', re.I)], []),
    ("Tailwind CSS", [re.compile(r'tailwindcss', re.I), re.compile(r'class="[^"]*?:[a-z-]+:\d+', re.I)], []),
    ("jQuery", [re.compile(r'jquery[-.](\d+\.\d+\.\d+)', re.I), re.compile(r'jQuery\.fn\.', re.I)], []),
    ("Alpine.js", [re.compile(r'alpinejs', re.I), re.compile(r'x-data', re.I)], []),
    ("htmx", [re.compile(r'htmx\.org', re.I), re.compile(r'hx-get', re.I), re.compile(r'hx-post', re.I)], []),
    ("Google Analytics", [re.compile(r'google-analytics\.com/analytics', re.I), re.compile(r'gtag\(', re.I)], []),
    ("Cloudflare", [], ["/cdn-cgi/"]),
    ("Nginx", [re.compile(r'nginx', re.I)], []),
]


@dataclass
class TechFinding:
    name: str
    confidence: str
    evidence: list[str] = field(default_factory=list)


class TechFingerprinter:
    def __init__(self):
        self._compiled: list[tuple[str, list[re.Pattern], list[str]]] = SIGNATURES

    def scan(self, html: str, headers: dict[str, str] | None = None) -> list[TechFinding]:
        results: list[TechFinding] = []
        html_lower = html.lower() if html else ""

        server = (headers or {}).get("Server", "") or (headers or {}).get("server", "") or ""
        x_powered = (headers or {}).get("X-Powered-By", "") or (headers or {}).get("x-powered-by", "") or ""

        for name, patterns, path_indicators in self._compiled:
            evidence: list[str] = []
            for p in patterns:
                m = p.search(html)
                if m:
                    evidence.append(m.group(0)[:80])
            for indicator in path_indicators:
                if indicator.lower() in html_lower:
                    evidence.append(f"path:{indicator}")

            if server and server.lower() in name.lower():
                evidence.append(f"server:{server}")
            if x_powered and name.lower() in x_powered.lower():
                evidence.append(f"x-powered:{x_powered}")

            if evidence:
                confidence = "high" if len(evidence) >= 2 else "medium"
                results.append(TechFinding(name=name, confidence=confidence, evidence=evidence))

        return results


def fingerprint_headers(headers: dict[str, str]) -> list[TechFinding]:
    results: list[TechFinding] = []
    server = headers.get("Server", "") or headers.get("server", "") or ""
    x_powered = headers.get("X-Powered-By", "") or headers.get("x-powered-by", "") or ""

    if server:
        results.append(TechFinding(name=f"Server: {server}", confidence="high", evidence=[f"Server: {server}"]))
    if x_powered:
        results.append(TechFinding(name=f"X-Powered-By: {x_powered}", confidence="high", evidence=[f"X-Powered-By: {x_powered}"]))

    return results
