"""Source-bound real-time calculus models consumed by the certificate kernel.

Arrival assumptions bound admitted invocations. Service assumptions bound available worker
time during backlogged intervals, not actual output. The kernel derives departures and every
resource effect from these two different premises and the complete typed outcome union.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Mapping, cast

from .curves import Curve, CurveError

if TYPE_CHECKING:
    from .contract import Contract, Task


class TemporalError(ValueError):
    pass


def rational(value: Any, label: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Fraction)):
        raise TemporalError(f"{label} must be a finite rational number")
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise TemporalError(f"{label} must be a finite rational number") from exc


def _fields(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise TemporalError(f"{label} must contain exactly {sorted(fields)}")
    return value


def _curve(value: Any, label: str) -> Curve:
    row = _fields(value, {"points", "tail_slope"}, label)
    try:
        if not isinstance(row["points"], list):
            raise TemporalError(f"{label}.points must be an array")
        points = []
        for point in row["points"]:
            if not isinstance(point, list) or len(point) != 2:
                raise TemporalError(f"{label}.points must contain [time_ms, value] pairs")
            points.append((rational(point[0], label), rational(point[1], label)))
        return Curve.from_points(points, rational(row["tail_slope"], label))
    except CurveError as exc:
        raise TemporalError(f"{label}: {exc}") from exc


def _monotone(curve: Curve, label: str) -> None:
    if curve.points[0][1] < 0 or curve.tail_slope < 0 or any(
        right[1] < left[1] for left, right in zip(curve.points, curve.points[1:])
    ):
        raise TemporalError(f"{label} must be nonnegative and nondecreasing")


def parse_temporal_spec(row: Mapping[str, Any]) -> Mapping[str, Any]:
    _fields(row, {
        "id", "kind", "envelopes", "flows", "expression", "operator", "bound",
        "start_ms", "end_ms", "metadata",
    }, "curve_bound")
    if not isinstance(row["operator"], str) or row["operator"] not in {"gte", "lte"}:
        raise TemporalError("curve_bound operator must be gte or lte")
    start = rational(row["start_ms"], "start_ms")
    end = None if row["end_ms"] is None else rational(row["end_ms"], "end_ms")
    if start < 0 or (end is not None and end < start):
        raise TemporalError("curve_bound requires 0 <= start_ms <= end_ms")
    rational(row["bound"], "bound")
    if not isinstance(row["envelopes"], list) or not row["envelopes"]:
        raise TemporalError("curve_bound requires nonempty envelopes")
    identifiers: set[str] = set()
    common = {"id", "kind", "task", "assumption", "horizon_ms", "failure_probability_upper"}
    for envelope in row["envelopes"]:
        if not isinstance(envelope, Mapping):
            raise TemporalError("envelope must be an object")
        kind = envelope.get("kind")
        if not isinstance(kind, str) or kind not in {"arrival", "service"}:
            raise TemporalError("envelope kind must be arrival or service")
        fields = (
            {"lower", "upper", "window"} if kind == "arrival"
            else {"availability", "slots", "duration_timing", "dispatch_timing"}
        )
        if kind == "service" and "outcomes" in envelope:
            fields.add("outcomes")
            outcomes = envelope["outcomes"]
            if (not isinstance(outcomes, list) or not outcomes
                or not all(isinstance(item, str) and item for item in outcomes)
                or len(set(outcomes)) != len(outcomes)):
                raise TemporalError("service outcomes must be a nonempty distinct source-type list")
        _fields(envelope, common | fields, "envelope")
        for name in ("id", "task", "assumption"):
            if not isinstance(envelope[name], str) or not envelope[name].strip():
                raise TemporalError(f"envelope {name} must be nonempty text")
        if envelope["id"] in identifiers:
            raise TemporalError(f"duplicate envelope {envelope['id']!r}")
        identifiers.add(envelope["id"])
        probability = rational(envelope["failure_probability_upper"], "envelope probability")
        if not 0 <= probability <= 1:
            raise TemporalError("envelope probability must be in [0, 1]")
        horizon = envelope["horizon_ms"]
        if horizon is not None and rational(horizon, "envelope horizon") <= 0:
            raise TemporalError("envelope horizon must be positive or null for all time")
        if kind == "arrival":
            if not isinstance(envelope["window"], str) or envelope["window"] not in {"prefix", "interval"}:
                raise TemporalError("arrival window must be prefix or interval")
            lower = _curve(envelope["lower"], "arrival lower")
            upper = _curve(envelope["upper"], "arrival upper")
            _monotone(lower, "arrival lower")
            _monotone(upper, "arrival upper")
            if lower.value(0) != 0:
                raise TemporalError("arrival lower must start at zero")
            try:
                ordered = upper.sub(lower).infimum() >= 0
            except CurveError:
                ordered = False
            if not ordered:
                raise TemporalError("arrival lower exceeds its upper envelope")
        else:
            for name in ("duration_timing", "dispatch_timing"):
                if not isinstance(envelope[name], str) or not envelope[name].strip():
                    raise TemporalError(f"service {name} must name a timing case")
            slots = rational(envelope["slots"], "service slots")
            if slots <= 0 or slots.denominator != 1:
                raise TemporalError("service slots must be a positive integer")
            availability = _curve(envelope["availability"], "service availability")
            _monotone(availability, "service availability")
            if availability.value(0) != 0:
                raise TemporalError("available worker time must start at zero")
            slopes = [availability.tail_slope] + [
                (right[1] - left[1]) / (right[0] - left[0])
                for left, right in zip(availability.points, availability.points[1:])
            ]
            if any(slope > slots for slope in slopes):
                raise TemporalError("service availability exceeds its allocated worker slots")
    if not isinstance(row["flows"], list) or not row["flows"]:
        raise TemporalError("curve_bound requires nonempty flows")
    flow_tasks: set[str] = set()
    for flow in row["flows"]:
        _fields(flow, {"task", "input", "service"}, "flow")
        if not isinstance(flow["task"], str) or flow["task"] in flow_tasks:
            raise TemporalError("flow tasks must be distinct identifiers")
        if not isinstance(flow["service"], str) or not flow["service"]:
            raise TemporalError("flow service must name an envelope")
        flow_tasks.add(flow["task"])
    return {key: value for key, value in row.items() if key not in {"id", "kind", "metadata"}}


def temporal_references(spec: Mapping[str, Any]) -> set[str]:
    references: set[str] = set()
    for envelope in spec["envelopes"]:
        references.add(f"task:{envelope['task']}")
        if envelope["kind"] == "service":
            for key in ("duration_timing", "dispatch_timing"):
                references.add(f"timing:{envelope['task']}/{envelope[key]}")
    return references


def temporal_failure_upper(spec: Mapping[str, Any]) -> Fraction:
    # An ID denotes one joint envelope event, regardless of how often it is referenced.
    return min(Fraction(1), sum((
        rational(envelope["failure_probability_upper"], "envelope probability")
        for envelope in temporal_premises(spec)
    ), Fraction(0)))


def temporal_premises(spec: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Each distinct source envelope or routing edge denotes one joint-window event."""
    premises: list[Mapping[str, Any]] = list(spec["envelopes"])
    for flow in spec["flows"]:
        value = flow["input"]
        if isinstance(value, Mapping):
            links = value.get("merge", [value["output"]] if "output" in value else [])
            if isinstance(links, list):
                for link in links:
                    if isinstance(link, Mapping):
                        premises.append(dict(link, id=f"handoff:{link.get('task')}->{flow['task']}"))
    return premises


def _lookahead(expression: Any) -> Fraction:
    if not isinstance(expression, Mapping):
        return Fraction(0)
    result = Fraction(0)
    for operator, operand in expression.items():
        children = operand if isinstance(operand, list) else [operand]
        ahead = max((_lookahead(child) for child in children), default=Fraction(0))
        if operator == "advance" and isinstance(operand, list) and len(operand) == 2:
            delay = rational(operand[1], "advance")
            if delay < 0:
                raise TemporalError("advance must be nonnegative")
            ahead += delay
        result = max(result, ahead)
    return result


@dataclass(frozen=True)
class FlowBounds:
    arrivals_lower: Curve
    arrivals_upper: Curve
    departures_lower: Curve
    departures_upper: Curve


class TemporalModel:
    def __init__(self, spec: Mapping[str, Any], contract: Contract) -> None:
        self.spec = spec
        self.contract = contract
        self.envelopes = {row["id"]: row for row in spec["envelopes"]}
        self.flows = {row["task"]: row for row in spec["flows"]}
        self.bounds: dict[str, FlowBounds] = {}
        self.visiting: set[str] = set()
        self.used_envelopes: set[str] = set()
        self.used_flows: set[str] = set()
        self.end = None if spec["end_ms"] is None else rational(spec["end_ms"], "end_ms")
        self.start = rational(spec["start_ms"], "start_ms")
        self.required_end = None if self.end is None else self.end + _lookahead(spec["expression"])

    def validate(self) -> None:
        workers: dict[str, Fraction] = {}
        acquisitions: dict[str, Fraction] = {}
        for task_id, flow in self.flows.items():
            task = self.contract.task_by_id.get(task_id)
            if task is None or task.role not in {"operation", "external"} or not task.outcomes:
                raise TemporalError(f"flow {task_id} requires a source-bound production task")
            envelope = self.envelopes.get(flow["service"])
            if envelope is None or envelope["kind"] != "service" or envelope["task"] != task_id:
                raise TemporalError(f"flow {task_id} must use its own service envelope")
            if not set(envelope.get("outcomes", task.outcome_by_type)) <= set(task.outcome_by_type):
                raise TemporalError(f"service {flow['service']} cites an outcome outside the source union")
            slots = rational(envelope["slots"], "slots")
            workers[task.worker] = workers.get(task.worker, Fraction(0)) + slots
            for resource in self.contract.resources:
                start = task.start_resources.get(resource.id)
                demand = max(
                    [Fraction(0) if start is None else rational(start.acquire, "acquire")]
                    + [rational(outcome.resources[resource.id].acquire, "acquire")
                       for outcome in task.outcomes if resource.id in outcome.resources]
                )
                acquisitions[resource.id] = acquisitions.get(resource.id, Fraction(0)) + slots * demand
            self.service(flow["service"])
        for worker, allocated in workers.items():
            if allocated > self.contract.worker_by_id[worker].concurrency:
                raise TemporalError(f"shared worker {worker} is overallocated: {allocated} slots")
        for resource_id, allocated in acquisitions.items():
            if allocated > rational(self.contract.resource_by_id[resource_id].capacity, "capacity"):
                raise TemporalError(f"shared resource {resource_id} is overallocated: {allocated}")
        self.expression(self.spec["expression"])
        if self.used_flows != set(self.flows):
            raise TemporalError(f"unused temporal flows: {sorted(set(self.flows) - self.used_flows)}")
        if self.used_envelopes != set(self.envelopes):
            raise TemporalError(f"unused temporal envelopes: {sorted(set(self.envelopes) - self.used_envelopes)}")

    def envelope(self, identifier: Any, kind: str) -> Mapping[str, Any]:
        if not isinstance(identifier, str) or identifier not in self.envelopes:
            raise TemporalError(f"unknown {kind} envelope {identifier!r}")
        row = self.envelopes[identifier]
        if row["kind"] != kind:
            raise TemporalError(f"envelope {identifier} is not a {kind} envelope")
        horizon = row["horizon_ms"]
        if horizon is not None and (
            self.required_end is None or self.required_end > rational(horizon, "horizon")
        ):
            raise TemporalError(f"envelope {identifier} does not cover the requested time window")
        self.used_envelopes.add(identifier)
        return cast(Mapping[str, Any], row)

    def service(self, identifier: Any) -> Curve:
        row = self.envelope(identifier, "service")
        task = self.contract.task_by_id.get(row["task"])
        if task is None:
            raise TemporalError(f"unknown service task {row['task']}")
        cost = Fraction(0)
        for key, metric in (("duration_timing", "duration"), ("dispatch_timing", "wait")):
            timing = task.timings.get(row[key])
            if (timing is None or timing.evidence != "assumed"
                or timing.metric != metric or timing.upper_ms is None):
                raise TemporalError(f"service {identifier} requires an assumed {metric} upper bound")
            cost += rational(timing.upper_ms, "service cost")
        if cost <= 0:
            raise TemporalError("service cost must be positive")
        # Up to one unfinished job per allocated lane. Dispatch cost is charged per job.
        return _curve(row["availability"], "availability").scale(1 / cost).sub(
            Curve.constant(rational(row["slots"], "slots"))
        ).maximum(Curve.constant(0))

    def flow(self, task_id: Any) -> FlowBounds:
        if not isinstance(task_id, str) or task_id not in self.flows:
            raise TemporalError(f"unknown temporal flow {task_id!r}")
        self.used_flows.add(task_id)
        if task_id in self.bounds:
            return self.bounds[task_id]
        if task_id in self.visiting:
            raise TemporalError(f"cyclic temporal flow at {task_id}")
        self.visiting.add(task_id)
        task = self.contract.task_by_id[task_id]
        row = self.flows[task_id]
        lower, upper = self.input(row["input"], task)
        result = FlowBounds(lower, upper, lower.convolution(self.service(row["service"])), upper)
        self.bounds[task_id] = result
        self.visiting.remove(task_id)
        return result

    def input(self, value: Any, task: Task) -> tuple[Curve, Curve]:
        if not isinstance(value, Mapping) or len(value) != 1:
            raise TemporalError("flow input must be arrival, output, or merge")
        kind, operand = next(iter(value.items()))
        if kind == "arrival":
            row = self.envelope(operand, "arrival")
            if row["task"] != task.id or task.typed_dependencies:
                raise TemporalError(f"arrival {operand} cannot bypass the typed inputs of {task.id}")
            return _curve(row["lower"], "arrival lower"), _curve(row["upper"], "arrival upper")
        if kind == "output":
            link = self.handoff(operand, task)
            upstream = self.contract.task_by_id.get(link["task"])
            edges = [edge for edge in task.typed_dependencies if edge.task == link["task"]]
            if upstream is None or len(edges) != 1 or len(task.typed_dependencies) != 1:
                raise TemporalError(f"output {operand!r} is not the sole typed input of {task.id}")
            bounds = self.flow(link["task"])
            guaranteed = self.outcome_types(upstream.id) == {edges[0].outcome_type}
            lower = bounds.departures_lower.shift(rational(link["delay_ms"], "handoff delay"))
            return lower if guaranteed else Curve.constant(0), bounds.departures_upper
        if kind == "merge":
            if not isinstance(operand, list) or len(operand) < 2:
                raise TemporalError("merge requires at least two upstream handoff premises")
            links = [self.handoff(item, task) for item in operand]
            source_ids = [link["task"] for link in links]
            if len(set(source_ids)) != len(source_ids):
                raise TemporalError("merge cannot double-count the same source")
            merge_edges = task.typed_dependencies
            groups = {edge.alternative_group for edge in merge_edges}
            if (set(source_ids) != {edge.task for edge in merge_edges} or None in groups or len(groups) != 1):
                raise TemporalError("merge requires exactly one typed alternative-producer group")
            lower, upper = Curve.constant(0), Curve.constant(0)
            for link in links:
                upstream_id = link["task"]
                upstream = self.contract.task_by_id[upstream_id]
                edge = next(edge for edge in merge_edges if edge.task == upstream_id)
                bounds = self.flow(upstream_id)
                if self.outcome_types(upstream.id) == {edge.outcome_type}:
                    lower = lower.add(bounds.departures_lower.shift(rational(link["delay_ms"], "handoff delay")))
                upper = upper.add(bounds.departures_upper)
            return lower, upper
        raise TemporalError(f"unknown flow input operator {kind!r}")

    def handoff(self, value: Any, task: Task) -> Mapping[str, Any]:
        row = _fields(value, {"task", "delay_ms", "assumption", "horizon_ms", "failure_probability_upper"}, "flow handoff")
        if not isinstance(row["task"], str) or not isinstance(row["assumption"], str) or not row["assumption"].strip():
            raise TemporalError("flow handoff requires a source task and explicit routing assumption")
        if rational(row["delay_ms"], "handoff delay") < 0:
            raise TemporalError("handoff delay must be nonnegative")
        probability = rational(row["failure_probability_upper"], "handoff probability")
        if not 0 <= probability <= 1:
            raise TemporalError("handoff probability must be in [0, 1]")
        horizon = row["horizon_ms"]
        if horizon is not None and (self.required_end is None or rational(horizon, "handoff horizon") < self.required_end):
            raise TemporalError(f"handoff to {task.id} does not cover the requested time window")
        return row

    def outcome_types(self, task_id: str) -> set[str]:
        service = self.envelopes[self.flows[task_id]["service"]]
        return set(service.get("outcomes", self.contract.task_by_id[task_id].outcome_by_type))

    def inventory(self, resource_id: Any, direction: str) -> Curve:
        resource = self.contract.resource_by_id.get(resource_id) if isinstance(resource_id, str) else None
        if resource is None:
            raise TemporalError(f"unknown inventory resource {resource_id!r}")
        lower = upper = Curve.constant(rational(resource.initial, "initial inventory"))
        for task in self.contract.tasks:
            legacy_effect = task.resources.get(resource.id)
            if not task.outcomes and legacy_effect is not None and (
                legacy_effect.produce or legacy_effect.consume
            ):
                raise TemporalError(f"inventory {resource_id} has an untyped affecting task {task.id}")
            start = task.start_resources.get(resource.id)
            deltas = []
            for outcome in task.outcomes:
                effect = outcome.resources.get(resource.id)
                deltas.append(Fraction(0) if effect is None else rational(effect.produce, "produce") - rational(effect.consume, "consume"))
            start_delta = Fraction(0) if start is None else rational(start.produce, "produce") - rational(start.consume, "consume")
            if not start_delta and not any(deltas):
                continue
            if task.id not in self.flows:
                raise TemporalError(f"inventory {resource_id} omits affecting task {task.id}")
            flow = self.flow(task.id)
            allowed_outcomes = self.outcome_types(task.id)
            deltas = [delta for delta, outcome in zip(deltas, task.outcomes) if outcome.type in allowed_outcomes]
            for minimum, maximum, count_lower, count_upper in (
                (start_delta, start_delta, flow.arrivals_lower, flow.arrivals_upper),
                (min(deltas), max(deltas), flow.departures_lower, flow.departures_upper),
            ):
                lower = lower.add((count_lower if minimum >= 0 else count_upper).scale(minimum))
                upper = upper.add((count_upper if maximum >= 0 else count_lower).scale(maximum))
        # This inference is for admitted, lossless resource flow. Never silently clamp to capacity:
        # doing so would incorrectly retain early production discarded by an overflowing bucket.
        try:
            capacity_safe = upper.supremum(0, self.required_end) <= rational(resource.capacity, "capacity")
        except CurveError:
            capacity_safe = False
        if not capacity_safe:
            raise TemporalError(f"inventory {resource_id} cannot exclude overflow; model admitted flow or discards")
        return lower if direction == "lower" else upper

    def expression(self, value: Any) -> Curve:
        if not isinstance(value, Mapping) or len(value) != 1:
            raise TemporalError("curve expression must contain exactly one operator")
        operator, operand = next(iter(value.items()))
        projections = {"arrivals_lower", "arrivals_upper", "departures_lower", "departures_upper"}
        if operator in projections:
            flow = self.flow(operand)
            return {"arrivals_lower": flow.arrivals_lower, "arrivals_upper": flow.arrivals_upper,
                    "departures_lower": flow.departures_lower, "departures_upper": flow.departures_upper}[operator]
        if operator == "service_lower":
            if not isinstance(operand, str) or operand not in self.flows:
                raise TemporalError("service_lower requires a flow task ID")
            self.flow(operand)
            return self.service(self.flows[operand]["service"])
        if operator in {"inventory_lower", "inventory_upper"}:
            return self.inventory(operand, operator.rsplit("_", 1)[1])
        if operator == "constant":
            return Curve.constant(rational(operand, "constant"))
        if operator in {"add", "min", "max"}:
            if not isinstance(operand, list) or len(operand) < 2:
                raise TemporalError(f"{operator} requires at least two curves")
            curves = [self.expression(item) for item in operand]
            result = curves[0]
            for curve in curves[1:]:
                result = {"add": result.add, "min": result.minimum, "max": result.maximum}[operator](curve)
            return result
        if not isinstance(operand, list) or len(operand) != 2:
            raise TemporalError(f"unknown curve operator or invalid pair {operator!r}")
        left = self.expression(operand[0])
        if operator == "scale":
            return left.scale(rational(operand[1], "scale"))
        if operator == "shift":
            return left.shift(rational(operand[1], "shift"))
        if operator == "advance":
            delay = rational(operand[1], "advance")
            if delay < 0:
                raise TemporalError("advance must be nonnegative")
            for envelope in self.envelopes.values():
                horizon = envelope["horizon_ms"]
                if horizon is not None and (self.end is None or self.end + delay > rational(horizon, "horizon")):
                    raise TemporalError("advanced curve exceeds an envelope's time window")
            points = [(Fraction(0), left.value(delay))]
            points.extend((time - delay, val) for time, val in left.points if time > delay)
            return Curve.from_points(points, left.tail_slope)
        right = self.expression(operand[1])
        if operator == "subtract":
            return left.sub(right)
        if operator == "convolve":
            return left.convolution(right)
        if operator == "deconvolve":
            # The supplied curves must bound all intervals needed by the unbounded supremum.
            if any(row["horizon_ms"] is not None for row in temporal_premises(self.spec)):
                raise TemporalError("unbounded deconvolution requires all-time envelope premises")
            if any(row["kind"] == "arrival" and row["window"] != "interval" for row in self.envelopes.values()):
                raise TemporalError("deconvolution requires interval arrival envelopes")
            return left.deconvolution(right)
        raise TemporalError(f"unknown curve operator {operator!r}")


def validate_temporal_spec(spec: Mapping[str, Any], contract: Contract) -> None:
    try:
        TemporalModel(spec, contract).validate()
    except CurveError as exc:
        raise TemporalError(str(exc)) from exc


def prove_temporal_bound(spec: Mapping[str, Any], contract: Contract) -> tuple[bool, str]:
    model = TemporalModel(spec, contract)
    try:
        model.validate()
        curve = model.expression(spec["expression"])
        bound = rational(spec["bound"], "bound")
        extremum = (curve.infimum(model.start, model.end) if spec["operator"] == "gte"
                    else curve.supremum(model.start, model.end))
        passed = extremum >= bound if spec["operator"] == "gte" else extremum <= bound
        return passed, f"exact curve extremum={extremum}; required {spec['operator']} {bound}; window=[{model.start}, {model.end if model.end is not None else 'infinity'}] ms"
    except (CurveError, TemporalError) as exc:
        return False, str(exc)
