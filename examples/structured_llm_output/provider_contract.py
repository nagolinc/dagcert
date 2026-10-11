"""Trusted pydantic-core interface, not an implementation of a JSON parser.

SchemaValidator uses the supplied core schema. validate_json(strict=True) returns
normally only for JSON satisfying it; invalid JSON, wrong fields/types, and invalid
schemas may raise Exception. The dependency supplies these semantic guarantees.
"""
from nagini_contracts.contracts import ContractOnly, Exsures


class SchemaValidator:
    @ContractOnly
    def __init__(self, schema: object) -> None:
        Exsures(Exception, True)
        ...

    @ContractOnly
    def validate_json(self, text: str, strict: bool = False) -> object:
        Exsures(Exception, True)
        ...
