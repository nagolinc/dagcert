from dataclasses import dataclass


@dataclass(frozen=True)
class RawUrl:
    value: str


@dataclass(frozen=True)
class ParsedUrl:
    path: str
