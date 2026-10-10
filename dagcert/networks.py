"""Quantity-valued curve programs with source-bound accounting obligations.

This is the general form of ``curve_bound``. Nodes are algebra expressions, not
invented application tasks. Leaves are ingress, available worker time, and
workload/ordering envelopes. No leaf can assert a derived output lower curve.
Semantic identities and state transitions are checked separately against source.
Arithmetic on distinct or repeated output quantities proves a numeric functional;
it does not silently create another physical stream, reserve, or matched prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from typing import Any, Mapping, TYPE_CHECKING, cast

from .curves import Curve, CurveError
from .quantities import quantity_service, ordered_prefix_lower, compose_monotone
from .relations import SourceRelation, parse_relation_predicate
from .scheduling import leftover_service, reserved_services, batch_work_demand

if TYPE_CHECKING:
    from .contract import Contract, Task


class NetworkError(ValueError):
    pass


def _number(value: Any, label: str) -> Fraction:
    from .temporal import rational

    try:
        return rational(value, label)
    except ValueError as exc:
        raise NetworkError(str(exc)) from exc


def _fields(row: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(row, Mapping) or set(row) != keys:
        raise NetworkError(f"{label} must contain exactly {sorted(keys)}")
    return row


def _curve(value: Any, label: str, *, cumulative: bool = True) -> Curve:
    from .temporal import _curve as parse_curve, _monotone

    try:
        curve = parse_curve(value, label)
        if cumulative:
            _monotone(curve, label)
        elif curve.infimum() < 0:
            raise NetworkError(f"{label} must be nonnegative")
        return curve
    except (ValueError, TypeError) as exc:
        raise NetworkError(f"{label}: {exc}") from exc


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NetworkError(f"{label} must be nonempty text")
    return value


def _names(value: Any, label: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or nonempty and not value:
        raise NetworkError(f"{label} must be a {'nonempty ' if nonempty else ''}array")
    names = [_text(item, label) for item in value]
    if len(set(names)) != len(names):
        raise NetworkError(f"{label} must be distinct")
    return names


def parse_network_spec(row: Mapping[str, Any]) -> Mapping[str, Any]:
    _fields(row, {"id", "kind", "network", "expression", "operator", "bound",
                  "start_ms", "end_ms", "metadata"}, "quantity curve bound")
    _fields(row["network"], {"envelopes", "relations", "invariants"}, "network")
    if row["kind"] != "curve_bound":
        raise NetworkError("network state claim kind must be curve_bound")
    _text(row["id"], "curve claim id")
    if not isinstance(row["metadata"], Mapping):
        raise NetworkError("network metadata must be an object")
    if row["operator"] not in ("gte", "lte"):
        raise NetworkError("curve operator must be gte or lte")
    start = _number(row["start_ms"], "start_ms")
    end = None if row["end_ms"] is None else _number(row["end_ms"], "end_ms")
    if start < 0 or end is not None and end < start:
        raise NetworkError("curve window must satisfy 0 <= start <= end")
    _number(row["bound"], "bound")
    network = row["network"]
    for key in ("envelopes", "relations", "invariants"):
        if not isinstance(network[key], list):
            raise NetworkError(f"network {key} must be an array")
    if not network["envelopes"]:
        raise NetworkError("network requires primitive envelopes")
    common = {"id", "kind", "assumption", "horizon_ms", "failure_probability_upper"}
    kinds = {
        "arrival": {"task", "input_field", "unit", "lower", "upper", "window"},
        "worker": {"worker", "tasks", "slots", "availability"},
        "workload": {"task", "unit", "outcome_quantities", "work_per_quantity",
                     "excess_work", "unfinished_work"},
        "withheld": {"task", "unit", "upper"},
        "allocation": {"server", "shares", "lag_work"},
        "policy": {"task", "mode"},
    }
    ids: set[str] = set()
    for envelope in network["envelopes"]:
        if (not isinstance(envelope, Mapping) or not isinstance(envelope.get("kind"), str)
            or envelope["kind"] not in kinds):
            raise NetworkError("unknown network envelope kind")
        kind = envelope["kind"]
        extra: set[str] = set()
        if kind == "policy":
            mode = envelope.get("mode")
            if mode in ("arbitrary", "strict_priority"):
                extra = {"interferers"}
            elif mode == "busy_period":
                extra = {"restart_delay_ms"}
            elif mode != "batching":
                raise NetworkError("policy mode must be arbitrary, strict_priority, batching, or busy_period")
        _fields(envelope, common | kinds[kind] | extra, f"{kind} envelope")
        identifier = _text(envelope["id"], "envelope id")
        if identifier in ids:
            raise NetworkError(f"duplicate network envelope {identifier}")
        ids.add(identifier)
        _text(envelope["assumption"], "envelope assumption")
        probability = _number(envelope["failure_probability_upper"], "envelope probability")
        if not 0 <= probability <= 1:
            raise NetworkError("envelope probability must be in [0,1]")
        if envelope["horizon_ms"] is not None and _number(envelope["horizon_ms"], "horizon") <= 0:
            raise NetworkError("envelope horizon must be positive or null for all time")
        if "unit" in envelope:
            _text(envelope["unit"], "quantity unit")
        if "task" in envelope:
            _text(envelope["task"], "envelope task")
        if kind == "arrival":
            if envelope["window"] not in ("prefix", "interval"):
                raise NetworkError("arrival window must be prefix or interval")
            lower, upper = (_curve(envelope[key], key) for key in ("lower", "upper"))
            try:
                ordered = upper.sub(lower).infimum() >= 0
            except CurveError:
                ordered = False
            if lower.value(0) != 0 or not ordered:
                raise NetworkError("arrival envelopes are unordered or lower does not start at zero")
            _text(envelope["input_field"], "arrival input_field")
            if not envelope["input_field"].isidentifier() or envelope["input_field"].startswith("__"):
                raise NetworkError("arrival input_field must identify a real source field")
        elif kind == "worker":
            _text(envelope["worker"], "worker id")
            slots = _number(envelope["slots"], "slots")
            if slots <= 0 or slots.denominator != 1:
                raise NetworkError("worker slots must be a positive integer")
            curve = _curve(envelope["availability"], "worker availability")
            slopes = [curve.tail_slope] + [
                (b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(curve.points, curve.points[1:])
            ]
            if curve.value(0) != 0 or any(slope > slots for slope in slopes):
                raise NetworkError("worker availability exceeds allocated physical worker time")
            _names(envelope["tasks"], "worker tasks")
        elif kind == "workload":
            if _number(envelope["work_per_quantity"], "work_per_quantity") <= 0:
                raise NetworkError("work_per_quantity must be positive")
            for key in ("excess_work", "unfinished_work"):
                if _number(envelope[key], key) < 0:
                    raise NetworkError(f"{key} must be nonnegative")
            if not isinstance(envelope["outcome_quantities"], Mapping):
                raise NetworkError("workload requires every source outcome's useful quantity")
        elif kind == "withheld":
            _curve(envelope["upper"], "withheld quantity upper", cumulative=False)
        elif kind == "allocation":
            _text(envelope["server"], "allocation server")
            for name in ("shares", "lag_work"):
                values = envelope[name]
                if not isinstance(values, Mapping) or not values:
                    raise NetworkError(f"allocation {name} must be a nonempty task/value object")
                for task, amount in values.items():
                    _text(task, f"allocation {name} task")
                    if _number(amount, name) < 0:
                        raise NetworkError(f"allocation {name} must be nonnegative")
        elif kind == "policy":
            if envelope["mode"] in ("arbitrary", "strict_priority"):
                _names(envelope["interferers"], "policy interferers", nonempty=False)
            elif envelope["mode"] == "busy_period":
                if _number(envelope["restart_delay_ms"], "restart delay") < 0:
                    raise NetworkError("restart delay must be nonnegative")
    invariants = network["invariants"]
    _names(invariants, "network invariants", nonempty=False)
    for relation in network["relations"]:
        _fields(relation, {"id", "task", "outcome", "predicate"}, "source relation")
        for key in ("id", "task", "outcome"):
            _text(relation[key], f"relation {key}")
        try:
            parse_relation_predicate(relation["predicate"])
        except ValueError as exc:
            raise NetworkError(str(exc)) from exc
    return {key: value for key, value in row.items() if key not in {"id", "kind", "metadata"}}


def network_references(spec: Mapping[str, Any]) -> set[str]:
    refs = {f"state-claim:{item}" for item in spec["network"]["invariants"]}
    for envelope in spec["network"]["envelopes"]:
        if "task" in envelope:
            refs.add(f"task:{envelope['task']}")
        refs.update(f"task:{task}" for task in envelope.get("tasks", []))
    refs.update(f"task:{item['task']}" for item in spec["network"]["relations"])
    return refs


def network_relations(spec: Mapping[str, Any], contract: Contract) -> list[SourceRelation]:
    tasks = contract.task_by_id
    result = [SourceRelation(row["id"], row["task"], row["outcome"], row["predicate"])
              for row in spec["network"]["relations"]]
    for envelope in spec["network"]["envelopes"]:
        if envelope["kind"] != "workload":
            continue
        task = tasks.get(envelope["task"])
        if task is None or task.role != "operation" or task.implementation is None or not task.outcomes:
            raise NetworkError("workload must bind a real source operation")
        quantities = envelope["outcome_quantities"]
        if set(quantities) != set(task.outcome_by_type):
            raise NetworkError(f"workload {envelope['id']} must account for every source outcome")
        if task.source_signature is not None and set(task.source_signature.outcome_types) != set(quantities):
            raise NetworkError(f"workload {envelope['id']} disagrees with the real source outcome union")
        for outcome, quantity in quantities.items():
            # An outcome produces zero, or an actual numeric source result field.
            if isinstance(quantity, (int, float)) and quantity == 0 and not isinstance(quantity, bool):
                continue
            if (not isinstance(quantity, str) or not quantity.startswith("result.")
                or not quantity[7:].isidentifier() or quantity[7:].startswith("_")):
                raise NetworkError("useful quantity must be zero or result.<numeric source field>")
            if task.source_signature is not None:
                fields = dict(dict(task.source_signature.outcome_fields).get(outcome, ()))
                if fields.get(quantity[7:]) not in ("int", "float"):
                    raise NetworkError(f"{task.id}/{outcome}: useful quantity is not a numeric source field")
            result.append(SourceRelation(
                f"quantity:{envelope['id']}:{outcome}", task.id, outcome,
                f"{quantity} >= 0 and {quantity} - {quantity} == 0",
            ))
    ids = [item.id for item in result]
    if len(set(ids)) != len(ids):
        raise NetworkError("network source relation IDs must be unique")
    for item in result:
        task = tasks.get(item.task_id)
        if (task is None or task.role != "operation" or task.implementation is None
            or item.outcome_type not in task.outcome_by_type):
            raise NetworkError(f"relation {item.id} must bind a real operation source outcome")
    return result


@dataclass(frozen=True)
class Signal:
    curve: Curve
    unit: str
    kind: str = "quantity"
    bound: str = "exact"
    tasks: frozenset[str] = frozenset()
    server: str | None = None
    interval: bool = False
    scope: str = "prefix"
    identity: str | None = None


_SERVICES = {"strict_work_service", "work_service", "quantity_service"}


def _direction(values: list[Signal], operator: str) -> str:
    directions = {value.bound for value in values} - {"exact"}
    if len(directions) > 1:
        raise NetworkError(f"{operator} cannot combine incompatible upper and lower bounds")
    return next(iter(directions), "exact")


def _scope(values: list[Signal]) -> str:
    scopes = {value.scope for value in values if value.kind != "constant"}
    if len(scopes) > 1:
        raise NetworkError("cannot mix cumulative-prefix and refill busy-period quantities")
    return next(iter(scopes), "prefix")


class NetworkModel:
    def __init__(self, spec: Mapping[str, Any], contract: Contract) -> None:
        parse_network_spec({"id": "validation", "kind": "curve_bound", "metadata": {}, **spec})
        self.spec, self.contract = spec, contract
        self.tasks = contract.task_by_id
        self.workers = contract.worker_by_id
        self.resources = contract.resource_by_id
        self.state_claims = contract.state_claim_by_id
        self.envelopes: dict[str, Mapping[str, Any]] = {
            row["id"]: cast(Mapping[str, Any], row) for row in spec["network"]["envelopes"]
        }
        self.used: set[str] = set()
        self.start = _number(spec["start_ms"], "start_ms")
        self.end = None if spec["end_ms"] is None else _number(spec["end_ms"], "end_ms")
        self.lookahead = Fraction(0)
        self.all_time = False

    def premise(self, identifier: Any, kind: str) -> Mapping[str, Any]:
        row = self.envelopes.get(identifier) if isinstance(identifier, str) else None
        if row is None or row["kind"] != kind:
            raise NetworkError(f"{identifier!r} must name a {kind} envelope")
        horizon = row["horizon_ms"]
        if horizon is not None and (
            self.all_time or self.end is None or self.end + self.lookahead > _number(horizon, "horizon")
        ):
            raise NetworkError(f"envelope {identifier} does not cover the requested window")
        self.used.add(identifier)
        return row

    def _policy(self, identifier: Any, modes: set[str]) -> Mapping[str, Any]:
        policy = self.premise(identifier, "policy")
        if policy["mode"] not in modes:
            raise NetworkError(f"policy {identifier!r} must declare one of {sorted(modes)}")
        return policy

    def _controller_invariant(self, task: str) -> None:
        for identifier in self.spec["network"]["invariants"]:
            claim = self.state_claims.get(identifier)
            if claim is not None and claim.kind == "relational_invariant" and any(
                transition["task"] == task for transition in claim.specification["transitions"]
            ):
                return
        raise NetworkError("refill busy-period policy requires a source-bound controller invariant")

    def validate(self) -> None:
        network_relations(self.spec, self.contract)
        workers: set[str] = set()
        resources: dict[str, Fraction] = {}
        tasks_by_worker: dict[str, list[Task]] = {}
        for registered_task in self.contract.tasks:
            tasks_by_worker.setdefault(registered_task.worker, []).append(registered_task)
        allocation_servers: set[str] = set()
        for row in self.envelopes.values():
            task = self.tasks.get(row["task"]) if "task" in row else None
            if "task" in row and (
                task is None or task.role != "operation" or task.implementation is None
            ):
                raise NetworkError(f"envelope {row['id']} needs a source-bound production task")
            if row["kind"] == "arrival":
                assert task is not None
                if task.typed_dependencies:
                    raise NetworkError("ingress cannot replace a source-owned upstream edge")
                if task.source_signature is not None and dict(task.source_signature.input_fields).get(row["input_field"]) not in ("int", "float"):
                    raise NetworkError("arrival quantity must identify a numeric source input field")
            if row["kind"] == "allocation":
                server = self.envelopes.get(row["server"])
                if server is None or server["kind"] != "worker":
                    raise NetworkError("allocation must identify a physical worker envelope")
                if server["id"] in allocation_servers:
                    raise NetworkError("one physical server cannot have multiple independently allocated reservation tables")
                allocation_servers.add(server["id"])
                if set(row["shares"]) != set(server["tasks"]) or set(row["lag_work"]) != set(server["tasks"]):
                    raise NetworkError("allocation shares and bounded lag must cover every server task")
                reserved_services(_curve(server["availability"], "worker service"), row["shares"], service_lag_work=row["lag_work"])
            if row["kind"] != "worker":
                continue
            worker = self.workers.get(row["worker"])
            if worker is None or worker.id in workers:
                raise NetworkError("declare each physical worker once, then share its service")
            workers.add(worker.id)
            slots = _number(row["slots"], "slots")
            if slots > worker.concurrency:
                raise NetworkError("available work exceeds actual worker concurrency")
            tasks = tasks_by_worker.get(worker.id, [])
            if set(row["tasks"]) != {task.id for task in tasks}:
                raise NetworkError("shared worker envelope must include every declared competing task")
            worker_acquisitions: dict[str, Fraction] = {}
            for task in tasks:
                for effects in [task.start_resources, task.resources, *(outcome.resources for outcome in task.outcomes)]:
                    for name, effect in effects.items():
                        worker_acquisitions[name] = max(
                            worker_acquisitions.get(name, Fraction(0)),
                            _number(effect.acquire, "resource acquisition"),
                        )
            for name, demand in worker_acquisitions.items():
                resources[name] = resources.get(name, Fraction(0)) + slots * demand
        for resource, demand in resources.items():
            if resource not in self.resources:
                raise NetworkError(f"worker uses undeclared physical resource {resource}")
            if demand > _number(self.resources[resource].capacity, "resource capacity"):
                raise NetworkError(f"shared physical resource {resource} is overallocated")
        for identifier in self.spec["network"]["invariants"]:
            from .induction import prove_inductive_invariant

            claim = self.state_claims.get(identifier)
            if claim is None or claim.kind != "relational_invariant":
                raise NetworkError("network invariants must cite source-bound relational invariants")
            passed, reason = prove_inductive_invariant(claim.specification, self.contract)
            if not passed:
                raise NetworkError(f"required invariant {identifier} fails: {reason}")
        signal = self.expression(self.spec["expression"])
        if signal.kind in _SERVICES:
            raise NetworkError("service capacity is not actual production; convolve with ingress or prove an explicit refill busy-period deficit")
        needed = "lower" if self.spec["operator"] == "gte" else "upper"
        if signal.bound not in (needed, "exact"):
            raise NetworkError(f"{self.spec['operator']} requires a {needed} bound, not {signal.bound}")
        if self.used != set(self.envelopes):
            raise NetworkError(f"unused network envelopes: {sorted(set(self.envelopes) - self.used)}")

    def expression(self, value: Any) -> Signal:
        if not isinstance(value, Mapping) or len(value) != 1:
            raise NetworkError("network expression must contain one operator")
        operator, operand = next(iter(value.items()))
        if operator in ("arrival_lower", "arrival_upper", "withheld_upper"):
            row = self.premise(operand, "withheld" if operator == "withheld_upper" else "arrival")
            bound = operator.rsplit("_", 1)[1]
            return Signal(
                _curve(row[bound], operator, cumulative=operator != "withheld_upper"), row["unit"],
                "withheld" if operator == "withheld_upper" else "ingress", bound,
                frozenset({row["task"]}), interval=row.get("window") == "interval",
                identity=f"withheld:{row['id']}" if operator == "withheld_upper" else f"input:{row['task']}:{row['input_field']}",
            )
        if operator == "worker_service":
            row = self.premise(operand, "worker")
            return Signal(_curve(row["availability"], "worker service"), "worker_ms", "strict_work_service",
                          "lower", frozenset(row["tasks"]), row["id"], True)
        if operator == "reserved_service":
            _fields(operand, {"allocation", "task"}, "reserved service")
            allocation = self.premise(operand["allocation"], "allocation")
            server_row = self.premise(allocation["server"], "worker")
            if set(allocation["shares"]) != set(server_row["tasks"]) or set(allocation["lag_work"]) != set(server_row["tasks"]):
                raise NetworkError("allocation shares and bounded lag must cover every server task")
            reservation_curves = reserved_services(
                _curve(server_row["availability"], "worker service"), allocation["shares"],
                service_lag_work=allocation["lag_work"],
            )
            task = _text(operand["task"], "reservation task")
            if task not in reservation_curves:
                raise NetworkError("reservation task is not on this server")
            # This explicit reservation premise guarantees share-minus-lag in
            # EVERY target-backlogged interval, hence strict per-class work.
            return Signal(reservation_curves[task], "worker_ms", "strict_work_service", "lower",
                          frozenset({task}), server_row["id"], True)
        if operator == "quantity_service":
            _fields(operand, {"work", "workload"}, "quantity service")
            work = self.expression(operand["work"])
            row = self.premise(operand["workload"], "workload")
            if work.unit != "worker_ms" or work.kind != "strict_work_service":
                raise NetworkError("quantity service requires strict per-class usable work; ordinary residual service is not a strict service premise")
            if work.tasks != frozenset({row["task"]}):
                raise NetworkError("quantity workload must match its allocated source task; a shared worker cannot be given in full to each task")
            curve = quantity_service(
                work.curve, work_per_quantity=row["work_per_quantity"],
                excess_work=row["excess_work"], unfinished_work=row["unfinished_work"],
            )
            if all(quantity == 0 for quantity in row["outcome_quantities"].values()):
                curve = Curve.constant(0)
            return Signal(curve, row["unit"], "quantity_service", "lower", work.tasks, work.server, True,
                          identity=f"output:{row['task']}:{row['unit']}:{json.dumps(row['outcome_quantities'], sort_keys=True)}")
        if operator == "leftover_service":
            _fields(operand, {"server", "cross_demand", "blocking_work", "policy"}, "leftover service")
            server, demand = self.expression(operand["server"]), self.expression(operand["cross_demand"])
            policy = self._policy(operand["policy"], {"arbitrary", "strict_priority"})
            if (server.kind != "strict_work_service" or server.unit != "worker_ms"
                or demand.unit != "worker_ms" or demand.bound != "upper" or not demand.interval
                or demand.kind in _SERVICES or server.server is None):
                raise NetworkError("leftover requires original strict worker service and interval work demand")
            physical = self.envelopes[server.server]
            if server.tasks != frozenset(physical["tasks"]):
                raise NetworkError("leftover must start with original aggregate service, not an already allocated share")
            target = policy["task"]
            interferers = frozenset(policy["interferers"])
            if target not in server.tasks or target in interferers or not interferers <= server.tasks:
                raise NetworkError("leftover policy target and interferers must belong to this server")
            if policy["mode"] == "arbitrary" and interferers != server.tasks - {target}:
                raise NetworkError("arbitrary multiplexing must account for every competing source task")
            if demand.tasks != interferers:
                raise NetworkError("cross demand must account for exactly the declared interfering tasks")
            return Signal(leftover_service(server.curve, demand.curve, blocking_work=operand["blocking_work"]),
                          "worker_ms", "work_service", "lower", frozenset({target}), server.server, True)
        if operator == "batch_work":
            _fields(operand, {"input", "batches", "unit_cost", "batch_cost", "flush_ms", "policy"}, "batch work")
            delay = _number(operand["flush_ms"], "batch flush delay")
            if delay < 0:
                raise NetworkError("batch flush delay must be nonnegative")
            self.lookahead += delay
            try:
                inputs = self.expression(operand["input"])
            finally:
                self.lookahead -= delay
            batches = self.expression(operand["batches"])
            policy = self._policy(operand["policy"], {"batching"})
            if (batches.unit != "count" or batches.bound != "upper" or not batches.interval
                or batches.kind not in {"ingress", "completed"}
                or inputs.bound != "upper" or not inputs.interval or inputs.kind not in {"ingress", "completed"}):
                raise NetworkError("batch work requires interval upper quantity and actual partial-batch release counts")
            if (inputs.kind in _SERVICES or batches.kind in _SERVICES
                or inputs.tasks != frozenset({policy["task"]}) or batches.tasks != inputs.tasks):
                raise NetworkError("batch work quantities must belong to the policy's actual source task")
            return Signal(batch_work_demand(
                inputs.curve, batches.curve, work_per_unit_upper=operand["unit_cost"],
                overhead_per_batch_upper=operand["batch_cost"], flush_delay_upper=operand["flush_ms"],
            ), "worker_ms", "work_demand", "upper", inputs.tasks, interval=True)
        if operator == "service_deficit":
            _fields(operand, {"demand", "service", "policy"}, "refill service deficit")
            demand, service = self.expression(operand["demand"]), self.expression(operand["service"])
            policy = self._policy(operand["policy"], {"busy_period"})
            self._controller_invariant(policy["task"])
            if (demand.bound != "upper" or not demand.interval or demand.kind in _SERVICES
                or demand.kind not in {"ingress", "completed"}
                or service.kind not in {"quantity_service", "strict_work_service"}
                or demand.unit != service.unit):
                raise NetworkError("refill deficit needs interval demand upper and matching strict usable service units")
            delayed_service = service.curve.shift(_number(policy["restart_delay_ms"], "restart delay"))
            return Signal(demand.curve.sub(delayed_service), demand.unit, "busy_period_deficit", "upper",
                          demand.tasks | service.tasks, scope="busy_period")
        if operator == "constant":
            _fields(operand, {"value", "unit"}, "quantity constant")
            return Signal(Curve.constant(_number(operand["value"], "constant")), _text(operand["unit"], "constant unit"), "constant")
        if operator in ("add", "min", "max"):
            if not isinstance(operand, list) or len(operand) < 2:
                raise NetworkError(f"{operator} needs at least two expressions")
            values = [self.expression(item) for item in operand]
            if len({item.unit for item in values}) != 1:
                raise NetworkError("cannot combine unlike quantity units")
            services = [item for item in values if item.kind in _SERVICES]
            if services and (
                operator == "add" or len(services) != len(values)
                or len({(item.kind, item.server, item.tasks, item.identity) for item in services}) != 1
            ):
                raise NetworkError("service capacity cannot be laundered into completed quantity arithmetic")
            direction = _direction(values, operator)
            scope = _scope(values)
            curve = values[0].curve
            for item in values[1:]:
                curve = {"add": curve.add, "min": curve.minimum, "max": curve.maximum}[operator](item.curve)
            # min of totals does NOT acquire keyed/prefix semantics. Such semantics
            # must be proved by the cited source relations/invariants.
            same_identity = values[0].identity is not None and all(item.identity == values[0].identity for item in values)
            kind = values[0].kind if services or operator in {"min", "max"} and same_identity else "quantity"
            return Signal(curve, values[0].unit, kind, direction,
                          frozenset().union(*(item.tasks for item in values)), values[0].server if services else None,
                          all(item.interval or item.kind == "constant" for item in values), scope,
                          values[0].identity if kind != "quantity" else None)
        if not isinstance(operand, list) or len(operand) != 2:
            raise NetworkError(f"unknown network operator or invalid operand {operator!r}")
        if operator == "compose":
            inner = self.expression(operand[1])
            if inner.unit != "ms" or inner.kind in _SERVICES:
                raise NetworkError("curve composition requires an explicit time-valued inner quantity, not service capacity")
            interval_end = None if self.all_time or self.end is None else self.end + self.lookahead
            try:
                required_outer_horizon = inner.curve.supremum(0, interval_end)
            except CurveError:
                required_outer_horizon = None
            previous = self.end, self.lookahead, self.all_time
            self.end, self.lookahead = required_outer_horizon, Fraction(0)
            self.all_time = required_outer_horizon is None
            try:
                outer = self.expression(operand[0])
            finally:
                self.end, self.lookahead, self.all_time = previous
            if outer.kind in _SERVICES:
                raise NetworkError("curve composition cannot treat service capacity as a quantity")
            return Signal(compose_monotone(outer.curve, inner.curve), outer.unit, "quantity",
                          _direction([outer, inner], operator), outer.tasks | inner.tasks,
                          scope=_scope([outer, inner]))
        previous_all_time = self.all_time
        if operator == "deconvolve":
            self.all_time = True
        try:
            left = self.expression(operand[0])
            if operator not in ("scale", "shift"):
                right = self.expression(operand[1])
        finally:
            self.all_time = previous_all_time
        if operator in ("scale", "shift"):
            amount = _number(operand[1], operator)
            if amount < 0:
                raise NetworkError(f"{operator} must be nonnegative")
            if operator == "scale" and left.kind in _SERVICES and amount > 1:
                raise NetworkError("scaling cannot manufacture extra physical service")
            preserves_quantity_bound = (
                operator == "scale" and (left.bound == "lower" and amount <= 1 or left.bound == "upper" and amount >= 1)
                or operator == "shift" and left.bound == "lower"
            )
            kind = left.kind if left.kind in _SERVICES or preserves_quantity_bound else "quantity"
            return Signal(left.curve.scale(amount) if operator == "scale" else left.curve.shift(amount),
                          left.unit, kind, left.bound, left.tasks, left.server, left.interval, left.scope,
                          left.identity if kind != "quantity" else None)
        if left.unit != right.unit:
            raise NetworkError("cannot combine unlike quantity units")
        if operator == "subtract":
            if left.kind in _SERVICES or right.kind in _SERVICES:
                raise NetworkError("subtracting service capacity as if it were completed output is invalid; use service_deficit with a refill policy")
            opposite = {"upper": "lower", "lower": "upper", "exact": "exact"}[right.bound]
            direction = _direction([left, Signal(right.curve, right.unit, bound=opposite)], operator)
            return Signal(left.curve.sub(right.curve), left.unit, "quantity", direction,
                          left.tasks | right.tasks, scope=_scope([left, right]))
        if operator == "convolve":
            if right.kind not in {"quantity_service", "strict_work_service", "work_service"}:
                raise NetworkError("departure convolution requires a source-bound service operand")
            if left.kind != "ingress" or left.bound != "lower" or left.tasks != right.tasks:
                raise NetworkError("departure convolution requires matching source task ingress lower, not spare capacity or another task's arrivals")
            return Signal(left.curve.convolution(right.curve), left.unit, "completed", "lower", right.tasks,
                          identity=right.identity or f"completed-work:{right.server}:{','.join(sorted(right.tasks))}")
        if operator == "deconvolve":
            if (left.bound != "upper" or not left.interval or left.kind != "ingress"
                or right.kind not in _SERVICES or left.tasks != right.tasks):
                raise NetworkError("departure deconvolution requires matching interval ingress upper and source-bound service")
            return Signal(left.curve.deconvolution(right.curve), left.unit, "completed", "upper", right.tasks, interval=True,
                          identity=right.identity or f"completed-work:{right.server}:{','.join(sorted(right.tasks))}")
        if operator == "ordered_prefix":
            if (left.bound != "lower" or right.bound != "upper" or right.kind != "withheld"
                or left.kind != "completed" or left.tasks != right.tasks):
                raise NetworkError("ordered prefix requires matching completed lower and total withheld upper")
            return Signal(ordered_prefix_lower(left.curve, right.curve), left.unit, "quantity", "lower", left.tasks)
        raise NetworkError(f"unknown network operator {operator}")


def prove_network_bound(spec: Mapping[str, Any], contract: Contract) -> tuple[bool, str]:
    try:
        model = NetworkModel(spec, contract)
        model.validate()
        signal = model.expression(spec["expression"])
        extremum = (signal.curve.infimum(model.start, model.end) if spec["operator"] == "gte"
                    else signal.curve.supremum(model.start, model.end))
        bound = _number(spec["bound"], "bound")
        passed = extremum >= bound if spec["operator"] == "gte" else extremum <= bound
        scope = (
            "elapsed time inside each refill busy period, conditional on the source controller/initial-reserve premise; not globally accumulated inventory"
            if signal.scope == "busy_period" else "cumulative-prefix quantities"
        )
        interpretation = (
            "derived numeric functional; no automatic physical production, inventory, or matched-prefix identity"
            if signal.kind == "quantity" else f"source-bound {signal.kind}"
        )
        return passed, f"source-bound quantity algebra: extremum={extremum} {signal.unit}; required {spec['operator']} {bound}; horizon={model.end if model.end is not None else 'infinity'} ms; scope={scope}; interpretation={interpretation}"
    except (NetworkError, CurveError, ValueError) as exc:
        return False, str(exc)
