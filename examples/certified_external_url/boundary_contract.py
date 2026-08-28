from nagini_contracts.contracts import ContractOnly, Ensures, Result

from types_model import ParsedUrl, RawUrl


@ContractOnly
def parse_url(
    request: RawUrl,
) -> ParsedUrl:
    Ensures(Result() is not None)
