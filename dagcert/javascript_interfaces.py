"""Closed JavaScript interface declarations matched against compiler evidence.

Parsing a declaration never establishes a proof. In particular, a record shape
does not establish that an arbitrary JavaScript object has no getters or proxy
effects; the backend must prove boundary provenance before emitting its shape.
"""

from dataclasses import dataclass
import json


PRIMITIVE_TYPES = frozenset({"boolean", "number", "string"})
EXECUTION_KINDS = frozenset({"synchronous", "asynchronous"})
RecordFields = tuple[tuple[str, str], ...]
RecordParameters = tuple[tuple[str, RecordFields], ...]


class JavaScriptInterfaceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JavaScriptInterface:
    execution: str
    parameters: tuple[tuple[str, str], ...]
    return_type: str
    record_parameters: RecordParameters = ()


def record_type_name(fields: RecordFields) -> str:
    """Canonical closed shape used for task input and typed-edge comparison."""
    return "record{" + ",".join(
        json.dumps(name, ensure_ascii=False) + ":" + type_name
        for name, type_name in fields
    ) + "}"


def _name(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise JavaScriptInterfaceError(f"{context} must be a nonempty name")
    return value


def _record_fields(value: object, context: str) -> RecordFields:
    if not isinstance(value, dict) or set(value) != {"kind", "fields"}:
        raise JavaScriptInterfaceError(f"{context} must contain exactly kind and fields")
    if value["kind"] != "record" or not isinstance(value["fields"], list):
        raise JavaScriptInterfaceError(f"{context} must declare a closed record")
    fields = []
    names = set()
    for field in value["fields"]:
        if not isinstance(field, dict) or set(field) != {"name", "type_name"}:
            raise JavaScriptInterfaceError(f"{context} fields require name and type_name")
        name = _name(field["name"], context + " field name")
        type_name = field["type_name"]
        if not isinstance(type_name, str) or type_name not in PRIMITIVE_TYPES:
            raise JavaScriptInterfaceError(f"{context} record fields require primitive types")
        if name in names:
            raise JavaScriptInterfaceError(f"{context} contains duplicate field {name!r}")
        names.add(name)
        fields.append((name, type_name))
    return tuple(sorted(fields))


def parse_javascript_interface(value: object, context: str) -> JavaScriptInterface:
    if not isinstance(value, dict) or set(value) != {"execution", "parameters", "return_type"}:
        raise JavaScriptInterfaceError(
            f"{context} must contain execution, parameters, and return_type"
        )
    execution = value["execution"]
    if not isinstance(execution, str) or execution not in EXECUTION_KINDS:
        raise JavaScriptInterfaceError(f"{context} requires synchronous or asynchronous execution")
    return_type = value["return_type"]
    if not isinstance(return_type, str) or return_type not in PRIMITIVE_TYPES | {"void"}:
        raise JavaScriptInterfaceError(
            f"{context} return_type must be primitive or void; async returns name the fulfilled value"
        )
    if not isinstance(value["parameters"], list):
        raise JavaScriptInterfaceError(f"{context} parameters must be an array")
    parameters = []
    records = []
    names = set()
    for parameter in value["parameters"]:
        if not isinstance(parameter, dict) or set(parameter) != {"name", "type"}:
            raise JavaScriptInterfaceError(f"{context} parameters require name and type")
        name = _name(parameter["name"], context + " parameter name")
        if name in names:
            raise JavaScriptInterfaceError(f"{context} contains duplicate parameter {name!r}")
        names.add(name)
        parameter_type = parameter["type"]
        if isinstance(parameter_type, str) and parameter_type in PRIMITIVE_TYPES:
            parameters.append((name, parameter_type))
        elif isinstance(parameter_type, dict):
            fields = _record_fields(parameter_type, context + " parameter " + name)
            parameters.append((name, record_type_name(fields)))
            records.append((name, fields))
        else:
            raise JavaScriptInterfaceError(
                f"{context} parameter types must be primitive or closed record descriptors; "
                "unsealed object, any, unknown, and void parameters are unsupported"
            )
    return JavaScriptInterface(execution, tuple(parameters), return_type, tuple(records))


def compiler_parameter_rows(interface: JavaScriptInterface) -> list[dict[str, object]]:
    """Return exact expected compiler rows, validating public API assertions too."""
    records = dict(interface.record_parameters)
    if len(records) != len(interface.record_parameters):
        raise JavaScriptInterfaceError("duplicate record parameter assertions")
    declaration_parameters = []
    for name, type_name in interface.parameters:
        if name in records:
            fields = records[name]
            if type_name != record_type_name(fields):
                raise JavaScriptInterfaceError("record shape does not match its task input type")
            parameter_type: object = {
                "kind": "record",
                "fields": [{"name": field, "type_name": kind} for field, kind in fields],
            }
        else:
            parameter_type = type_name
        declaration_parameters.append({"name": name, "type": parameter_type})
    parsed = parse_javascript_interface({
        "execution": interface.execution,
        "parameters": declaration_parameters,
        "return_type": interface.return_type,
    }, "compiler interface assertion")
    if parsed != interface:
        raise JavaScriptInterfaceError("compiler interface assertion is not canonical or has unused records")
    rows: list[dict[str, object]] = []
    for name, type_name in interface.parameters:
        if name in records:
            rows.append({"name": name, "descriptor": {
                "kind": "record",
                "fields": [{"name": field, "type_name": kind} for field, kind in records[name]],
            }})
        else:
            rows.append({"name": name, "type_name": type_name})
    return rows
