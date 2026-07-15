import re

SITEMAP_LOC_RE = re.compile(r'<loc>([^<]+)</loc>')


def parse_sitemap(xml_text: str) -> list[str]:
    return SITEMAP_LOC_RE.findall(xml_text)
