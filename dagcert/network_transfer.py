"""Source-bound substitutions between quantity-valued network expressions.

The algebraic result is reused unchanged (apart from an explicit transport
delay or verified change of measurement). No new arrival curve is assumed at
an internal edge, and zero-producing outcomes cannot disappear during mapping.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Mapping, TYPE_CHECKING

from .curves import Curve
from .relations import SourceRelation

if TYPE_CHECKING:
    from .contract import Contract, Task


class TransferError(ValueError):
    pass


def measurement(
    identifier: str, envelopes: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    row = envelopes.get(identifier)
    if row is None or row["kind"] not in {"workload", "quantity_map"}:
        raise TransferError(f"{identifier!r} must name a source-bound quantity measurement")
    return row


def quantity_field(task: Task, outcome: str, value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
        return None
    if (not isinstance(value, str) or not value.startswith("result.")
        or not value[7:].isidentifier() or value[7:].startswith("_")):
        raise TransferError("quantity measurement must be zero or result.<numeric source field>")
    if task.source_signature is None:
        raise TransferError("quantity measurement requires compiler-extracted source fields")
    fields = dict(dict(task.source_signature.outcome_fields).get(outcome, ()))
    if fields.get(value[7:]) not in {"int", "float"}:
        raise TransferError(f"{task.id}/{outcome}: quantity is not a numeric source field")
    return value[7:]


def map_relations(
    row: Mapping[str, Any], envelopes: Mapping[str, Mapping[str, Any]], contract: Contract,
) -> list[SourceRelation]:
    """Obligations bind exact rational conversion to actual returned values."""
    from .temporal import rational

    source = measurement(row["source"], envelopes)
    if source["task"] != row["task"]:
        raise TransferError("quantity conversion must measure the same source task outcomes")
    task = contract.task_by_id.get(row["task"])
    if task is None or task.role != "operation" or task.implementation is None:
        raise TransferError("quantity conversion needs a source-bound operation")
    old, new = source["outcome_quantities"], row["outcome_quantities"]
    if set(old) != set(new) or set(new) != set(task.outcome_by_type):
        raise TransferError("quantity conversion must account for every source outcome")
    factor = rational(row["factor"], "quantity conversion factor")
    if factor < 0:
        raise TransferError("quantity conversion factor must be nonnegative")
    result: list[SourceRelation] = []
    for outcome in new:
        old_field, new_field = quantity_field(task, outcome, old[outcome]), quantity_field(task, outcome, new[outcome])
        old_value, new_value = old[outcome] if old_field else "0", new[outcome] if new_field else "0"
        result.append(SourceRelation(
            f"quantity-map:{row['id']}:{outcome}", task.id, outcome,
            f"{new_value} >= 0 and {new_value} - {new_value} == 0 and "
            f"{factor.denominator} * {new_value} == {factor.numerator} * {old_value}",
        ))
    return result


def validate_transfer(
    row: Mapping[str, Any], envelopes: Mapping[str, Mapping[str, Any]], contract: Contract,
) -> tuple[str, ...]:
    """Resolve every useful outcome to an existing, source-typed production edge."""
    from .temporal import rational

    source = measurement(row["source"], envelopes)
    producer = contract.task_by_id.get(source["task"])
    consumer = contract.task_by_id.get(row["task"])
    if producer is None or consumer is None:
        raise TransferError("quantity transfer references an unknown producer or consumer")
    if producer.id == consumer.id:
        raise TransferError("quantity transfer must cross a declared task edge")
    useful = {
        outcome: quantity_field(producer, outcome, value)
        for outcome, value in source["outcome_quantities"].items()
    }
    useful = {outcome: field for outcome, field in useful.items() if field is not None}
    if set(row["bindings"]) != set(useful):
        raise TransferError("transfer bindings must cover exactly every producing source outcome")
    projections: set[str] = set()
    for outcome, field in useful.items():
        binding = row["bindings"][outcome]
        if not isinstance(binding, Mapping):
            raise TransferError("transfer binding must select an existing typed edge")
        kind = binding.get("kind")
        if kind == "dependency" and set(binding) == {"kind", "input_field"}:
            input_field = binding["input_field"]
            if input_field is not None and not isinstance(input_field, str):
                raise TransferError("dependency transfer input_field must be a source field or null")
            if not any(edge.task == producer.id and edge.outcome_type == outcome and edge.input_field == input_field
                       for edge in consumer.typed_dependencies):
                raise TransferError("quantity transfer must follow the actual typed dependency")
            if consumer.source_signature is None:
                raise TransferError("quantity transfer needs compiler-extracted destination types")
            actual_type = consumer.input_type if input_field is None else dict(consumer.source_signature.input_fields).get(input_field)
            if actual_type != outcome:
                raise TransferError("dependency transfer must preserve the whole source-typed payload")
            projections.add(f"input.{field}" if input_field is None else f"input.{input_field}.{field}")
        elif kind == "channel" and set(binding) == {"kind", "id"}:
            if not isinstance(binding["id"], str):
                raise TransferError("channel transfer id must be text")
            channel = contract.channel_by_id.get(binding["id"])
            if (channel is None or channel.enqueue.task != producer.id
                or channel.enqueue.outcome_type != outcome or channel.dequeue.task != consumer.id):
                raise TransferError("quantity transfer must follow the actual typed channel")
            if (channel.payload_type != outcome or consumer.source_signature is None
                or dict(consumer.source_signature.input_fields).get(channel.dequeue.input_field) != outcome):
                raise TransferError("channel transfer must preserve the compiler-extracted payload type")
            projections.add(f"input.{channel.dequeue.input_field}.{field}")
        elif kind == "external_handoff" and set(binding) == {"kind", "id"}:
            if not isinstance(binding["id"], str):
                raise TransferError("external handoff transfer id must be text")
            handoff = contract.external_handoff_by_id.get(binding["id"])
            if (handoff is None or handoff.source.task != producer.id
                or handoff.source.outcome_type != outcome or handoff.source.output_field != field
                or handoff.destination.task != consumer.id):
                raise TransferError("quantity transfer must follow the actual external quantity field")
            if rational(row["delay_ms"], "transfer delay") < rational(handoff.upper_ms, "external delay"):
                raise TransferError("transfer delay cannot understate its external handoff")
            if rational(row["failure_probability_upper"], "transfer failure") < rational(handoff.bad_event_probability_upper, "external failure"):
                raise TransferError("transfer failure budget cannot understate its external handoff")
            projections.add(f"input.{handoff.destination.input_field}")
        else:
            raise TransferError("transfer binding must select dependency, channel, or external_handoff")
    return tuple(sorted(projections))


def conservation_relations(
    workload: Mapping[str, Any], input_quantities: tuple[str, ...], contract: Contract,
) -> list[SourceRelation]:
    """Ordinary departures require conserved arrivals, not just useful capacity.

    A zero-output failure with positive input cannot satisfy this rule. Such a
    system needs a separate retained-backlog/ retry induction proof; silently
    treating dropped work as pending useful work would invalidate convolution.
    """
    task = contract.task_by_id[workload["task"]]
    if len(input_quantities) != 1:
        raise TransferError("departure convolution requires one source-bound input quantity projection")
    input_value = input_quantities[0]
    result = []
    for outcome, quantity in workload["outcome_quantities"].items():
        field = quantity_field(task, outcome, quantity)
        output_value = quantity if field else "0"
        result.append(SourceRelation(
            f"conservation:{workload['id']}:{outcome}:{input_value}", task.id, outcome,
            f"{input_value} < 0 or {output_value} == {input_value}",
        ))
    return result


def advance_upper(curve: Curve, amount: Fraction) -> Curve:
    """alpha(t+d): bounded jitter expands an EVERY-INTERVAL arrival upper."""
    points = [(Fraction(0), curve.value(amount))]
    points.extend((time - amount, value) for time, value in curve.points if time > amount)
    return Curve(tuple(points), curve.tail_slope)
