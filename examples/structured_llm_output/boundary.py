"""Validate model text using an established dependency."""
from dagcert.runtime import external_boundary
from pydantic_core import SchemaValidator


@external_boundary("llm.plan.validate")
def validate_plan(text: str) -> bool:
    try:
        validator = SchemaValidator({
            "type": "typed-dict",
            "fields": {
                "title": {"type": "typed-dict-field", "schema": {"type": "str"}},
                "summary": {"type": "typed-dict-field", "schema": {"type": "str"}},
            },
            "extra_behavior": "allow",
        })
        validator.validate_json(text, strict=True)
        return True
    except Exception:
        return False
