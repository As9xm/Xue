import re
from dataclasses import dataclass, field


@dataclass
class SeoReport:
    url: str
    title: str = ""
    title_length: int = 0
    meta_description: str = ""
    meta_description_length: int = 0
    h1_count: int = 0
    h1_tags: list[str] = field(default_factory=list)
    has_canonical: bool = False
    canonical_url: str = ""
    meta_robots: str = ""
    images_without_alt: int = 0
    images_with_alt: int = 0
    has_open_graph: bool = False
    has_twitter_cards: bool = False
    heading_issues: list[str] = field(default_factory=list)
    language: str = ""


def analyze_seo(html: str, url: str) -> SeoReport:
    report = SeoReport(url=url)

    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I | re.S)
    if title_match:
        report.title = title_match.group(1).strip()
        report.title_length = len(report.title)

    desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', html, re.I)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']', html, re.I)
    if desc_match:
        report.meta_description = desc_match.group(1).strip()
        report.meta_description_length = len(report.meta_description)

    h1_matches = re.findall(r'<h1[^>]*>(.*?)</h1>', html, re.I | re.S)
    report.h1_count = len(h1_matches)
    for h1 in h1_matches:
        clean = re.sub(r'<[^>]+>', '', h1).strip()
        if clean:
            report.h1_tags.append(clean)

    if report.h1_count == 0:
        report.heading_issues.append("No <h1> tag found")
    elif report.h1_count > 1:
        report.heading_issues.append(f"Multiple <h1> tags ({report.h1_count})")

    canonical = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']*)["\']', html, re.I)
    if not canonical:
        canonical = re.search(r'<link[^>]+href=["\']([^"\']*)["\'][^>]+rel=["\']canonical["\']', html, re.I)
    if canonical:
        report.has_canonical = True
        report.canonical_url = canonical.group(1)

    robots = re.search(r'<meta[^>]+name=["\']robots["\'][^>]+content=["\']([^"\']*)["\']', html, re.I)
    if not robots:
        robots = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']robots["\']', html, re.I)
    if robots:
        report.meta_robots = robots.group(1).strip()

    img_matches = re.findall(r'<img[^>]*>', html, re.I)
    for img in img_matches:
        has_alt = re.search(r'alt\s*=', img, re.I)
        if has_alt:
            alt_value = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img, re.I)
            if alt_value and alt_value.group(1).strip():
                report.images_with_alt += 1
            else:
                report.images_without_alt += 1
        else:
            report.images_without_alt += 1

    og = re.search(r'<meta[^>]+property=["\']og:', html, re.I)
    report.has_open_graph = bool(og)

    tc = re.search(r'<meta[^>]+name=["\']twitter:', html, re.I)
    report.has_twitter_cards = bool(tc)

    lang = re.search(r'<html[^>]+lang=["\']([^"\']+)["\']', html, re.I)
    if lang:
        report.language = lang.group(1)

    return report
