import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class ExtractedContent:
    title: str = ""
    text: str = ""
    word_count: int = 0
    char_count: int = 0
    paragraphs: list[str] = field(default_factory=list)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._text_parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._text_parts.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._text_parts)
        raw = re.sub(r'\n+', '\n', raw)
        raw = re.sub(r' {2,}', ' ', raw)
        return raw.strip()


def extract_text(html: str) -> ExtractedContent:
    if not html:
        return ExtractedContent()

    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass

    text = extractor.get_text()

    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I | re.S)
    title = title_match.group(1).strip() if title_match else ""

    words = text.split()
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    return ExtractedContent(
        title=title,
        text=text,
        word_count=len(words),
        char_count=len(text),
        paragraphs=paragraphs,
    )
