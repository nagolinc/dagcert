from urllib.parse import unquote

from dagcert.runtime import external_boundary


@external_boundary("stdlib.url.unquote")
def decode_url_component(value: str) -> str:
    return unquote(value)

