import re

# A base URL that is safe to hand back inside a shell command: scheme, a hostname or a
# bracketed IPv6 literal, an optional port, an optional mount path. Nothing a shell reads as
# syntax, and no userinfo, query, or fragment.
_PLAIN_HTTP_URL = re.compile(
    r"https?://(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9.-]+)(:\d{1,5})?(/[A-Za-z0-9._~/-]*)?"
)


def is_plain_http_url(value: str) -> bool:
    return _PLAIN_HTTP_URL.fullmatch(value) is not None
