from urllib.parse import parse_qsl, urldefrag, urlencode, urlparse, urlunparse


def normalize_url(url: str, strip_www: bool = True, lower_case: bool = True,
                  sort_query: bool = True, remove_trailing_slash: bool = True,
                  remove_fragment: bool = True) -> str:
    if remove_fragment:
        url, _ = urldefrag(url)

    parsed = urlparse(url)

    scheme = parsed.scheme.lower() if lower_case else parsed.scheme

    netloc = parsed.netloc.lower() if lower_case else parsed.netloc
    if strip_www and netloc.startswith("www."):
        netloc = netloc[4:]

    path = parsed.path
    if remove_trailing_slash and path.endswith("/") and path != "/":
        path = path.rstrip("/")

    params = parsed.params

    query = parsed.query
    if sort_query and query:
        qs = parse_qsl(query, keep_blank_values=True)
        qs.sort(key=lambda x: x[0])
        query = urlencode(qs)

    fragment = "" if remove_fragment else parsed.fragment

    return urlunparse((scheme, netloc, path, params, query, fragment))
