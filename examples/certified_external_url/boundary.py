from urllib.parse import urlsplit

from dagcert.runtime import external_boundary

from types_model import ParsedUrl, RawUrl


@external_boundary("url.parse")
def parse_url(request: RawUrl) -> ParsedUrl:
    """The executable adapter calls the real standard-library provider."""
    return ParsedUrl(urlsplit(request.value).path)
