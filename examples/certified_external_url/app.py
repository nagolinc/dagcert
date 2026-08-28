from dagcert.runtime import operation

from types_model import ParsedUrl


@operation
def accept_parsed_url(request: ParsedUrl) -> ParsedUrl:
    return request
