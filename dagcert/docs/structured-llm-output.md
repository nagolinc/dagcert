# structuredLLMOutput: an LLM returns a usable structure or fails

**Recognize this immediately:** "I call an LLM and expect structured output" is this recipe.
Start here, before designing a proof or changing a verifier:

```text
dagcert --help structuredLLMOutput
dagcert help structuredLLMOutput
```

Both commands display this same guide. The existing primitive is
`dagcert.runtime.external_boundary`. **Do not invent a structured-output primitive, a recursive
JSON representation, or a parser proof.** Use a real schema validator, its explicit external
contract, and a small application operation that returns a usable result or failure.

## Copy the working example first

The complete example is `examples/structured_llm_output/`. Its production adapter and operation
are fewer than 70 lines together. It uses the real `pydantic-core` validator; it does not fake a
schema check. The adapter checks a JSON object with required string fields `title` and `summary`
and allows additional fields. The operation preserves the exact input JSON on success.

```text
python -m pip install "dagcert[structured-output] @ git+https://github.com/nagolinc/dagcert.git"
python -m examples.structured_llm_output.verify PATH_TO_MALEDICTUS
```

From a repository checkout, install with `python -m pip install -e ".[structured-output]"`.
Use an already configured Maledictus executable with its required strict-mypy/contract runtime.
The verifier command pins that executable's SHA-256, invokes Dagcert's real source checker, and
writes `.cache/structured-llm-output/source-proof.json`. Nonzero exit means the example has not
passed. It does not invoke a live model, issue a streaming certificate, or claim a timing bound.

Before this recipe was published, that command passed with Maledictus executable SHA-256
`0b66dba6d95f5191fab09762bc902e0dc852d85b55622fc1555e1621f2634c40` and pydantic-core `2.50.1`.
The retained source check establishes type/exception closure and source/provider binding.
Behavior tests separately exercise valid JSON, malformed JSON, missing fields, wrong field/root
types, provider failure, and every non-success outcome. Schema semantics are an explicit trusted
dependency guarantee. These are separate facts; none is a composed application certificate.

The example starts with **model response text** to keep it runnable without credentials or model
latency. In your application, keep the actual LLM call and its failures before this validation
step, inside the same timed task. Do not replace production calls with this example's test inputs.

## The exact existing API

An adapter declares its ordinary return type. The decorator wraps it at runtime:

```python
from dagcert.runtime import external_boundary

@external_boundary("llm.plan.validate")
def validate_plan(text: str) -> bool:
    # Call your established validator here, using the consumer's schema.
    # The complete runnable body is shown below.
    ...
```

Callers receive `ExternalSuccess[bool] | ExternalRaised | ExternalTypeViolation`.
**Do not annotate the decorated implementation as returning `ExternalSuccess` or `ExternalResult`:**
the implementation returns `bool`; the decorator supplies the envelope.

| Outcome | Meaning | Task action |
| --- | --- | --- |
| `ExternalSuccess(True)` | The adapter returned `True` after successful validation | Return `PlanReady` for that exact response |
| `ExternalSuccess(False)` | The adapter ran and reported validation failure | Return `PlanFailed`; zero useful output |
| `ExternalRaised` | The adapter raised unexpectedly at runtime | Return `PlanFailed`; retain the diagnostic |
| `ExternalTypeViolation` | An input or output violated the adapter's annotated type | Return `PlanFailed`; retain the violation |

**`ExternalSuccess` means the adapter returned its declared type. It does not mean the domain
operation succeeded.** `ExternalSuccess(False)` is a failed schema check. Checking only
`isinstance(result, ExternalSuccess)` would incorrectly accept it.

`Validated[T] | Failure` is the conceptual contract. `Validated` is not a Dagcert API to import.
Use concrete application outcomes such as `PlanReady | PlanFailed`. A dataclass/type check is
not a replacement for schema validation; the actual validator supplies the schema guarantee.

## 1. Adapter: call the library, convert expected errors to data

This is the runnable example's `boundary.py`:

```python
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
```

**Catch expected provider/validation exceptions in the source adapter.** Although
`external_boundary` also catches exceptions at runtime, the checked adapter body must satisfy
its proof obligations. Relying on the runtime decorator alone is not sufficient for this recipe.
The provider contract below declares these exceptions; it does not pretend validation never fails.

This validator uses **Pydantic core schema**, not JSON Schema syntax. Change the fields according
to that library's API. If the app already uses JSON Schema or another established validator,
retain that library and bind its real interface instead of translating schemas unnecessarily.
Choose only the schema the consumer needs: do not add output/context caps, arbitrary constraints,
or lossy conversions to make verification easier. Returning the original validated text here
preserves extra metadata; consumers that need typed objects should keep their actual typed API.

## 2. Task: branch on the result, nothing more

This is the runnable example's `app.py`:

```python
from dataclasses import dataclass
from dagcert.runtime import ExternalRaised, ExternalSuccess, ExternalTypeViolation, operation
from boundary import validate_plan

@dataclass(frozen=True)
class ModelResponse:
    text: str

@dataclass(frozen=True)
class PlanReady:
    plan_json: str

@dataclass(frozen=True)
class PlanFailed:
    reason: str

@operation
def accept_model_response(request: ModelResponse) -> PlanReady | PlanFailed:
    result = validate_plan(request.text)
    if isinstance(result, ExternalSuccess):
        if result.value:
            return PlanReady(request.text)
        return PlanFailed("response did not satisfy the schema")
    if isinstance(result, ExternalRaised):
        return PlanFailed(result.exception_type)
    if isinstance(result, ExternalTypeViolation):
        return PlanFailed(result.observed_type)
    return PlanFailed("unrecognized external outcome")
```

For the full LLM task, put the existing source-bound model adapter call before validation. Handle
provider refusal, transport failure, and unusable responses as `PlanFailed`. Only pass the actual
successful response to this validator. Both adapters belong in the task's `external_calls` list;
an ordinary synchronous call does not need another worker, queue, or DAG task. See
`dagcert help multi-external-worker` for several provider calls inside one operation.

## 3. Provider contract: describe the library, do not reimplement it

`provider_contract.py` contains the real library's signatures and exceptional exits:

```python
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
```

The external assumption explicitly states that `SchemaValidator` uses the supplied schema and
that strict `validate_json` returns normally only for JSON satisfying it. Invalid JSON, mismatched
fields/types, and library errors may raise. Bind the dependency/version and this assumption.
The proof uses that sealed interface; it does not prove the library's parser or validation loops.
Do not turn the assumption into a claim that the LLM always succeeds or is fast enough.

## 4. Wire it into the contract

Copy the complete `dag_contract.json` from the example. The important connections are:

```json
{
  "id": "llm.plan.validate",
  "implementation": {
    "language": "python", "path": "boundary.py", "symbol": "validate_plan"
  },
  "stub_path": "provider_contract.py",
  "assumption": "The pinned validator checks the supplied schema; invalid inputs may fail.",
  "provider": {"module": "pydantic_core", "symbols": ["SchemaValidator"]},
  "exception_policy": "declared-by-exsures"
}
```

Put that entry in top-level `external_boundaries`. The operation task declares
`"external_calls": ["llm.plan.validate"]` and binds `app.py:accept_model_response`.
The literal ID must match the decorator. Dagcert checks the real import/call edge, adapter,
provider, stub, and source hashes. An unused declaration or an assumed application-owned parser
is not an external library contract. The excerpt is not a whole contract; copy the example's
complete file to retain the required v12 fields.

## What to change for your application

1. Keep your real model request, model/configuration, and existing retry policy.
2. Replace the example fields with exactly the schema required downstream. Bind any dynamic
   schema/request parameters too; do not silently replace them with this fixed demonstration.
3. Keep the actual response identity through validation and the returned success record.
4. Rename the task, worker, concrete records, and boundary IDs; update both source and contract.
5. Run the source check immediately. Test one valid response and the ordinary failure cases.
6. Only after that passes, measure the real invocation and compose it with the next microclaim.

## Timing, retries, resources, and credit

Start the task clock **before the model call**, and stop after outcome classification. Every
attempt occupies its real worker/resources and costs elapsed time, including invalid JSON,
schema mismatch, refusal, transport errors, repair requests, and exhausted retries.

Only `PlanReady` produces a useful plan resource. `PlanFailed` produces zero. The boundary monitor
records elapsed time on every adapter invocation, but its `succeeded` flag describes the typed
adapter return, not useful-plan production. In this example, `ExternalSuccess(False)` is timed
normally and must still count against the task's success rate. Use the task outcome for credit.
Do not sum nested boundary durations and the enclosing task duration as separate elapsed work.

The example has no timing bound or failure-rate assumption. Supply real measurements and explicit
engineering premises for your application; a quick schema check says nothing about model latency
or backend video throughput. Do not run browsers to prove a backend-only claim.

## If the first check fails: stop locally

| Symptom | First action |
| --- | --- |
| Undeclared exceptional exit from the adapter | Catch the declared error and return an explicit negative result, as above |
| Type violation | Fix the actual adapter annotation/return value; never relabel it as useful output |
| Missing/unused external boundary | Match decorator ID, declared task call, source path, provider symbol, and stub |
| Wrong schema/result identity | Correct the application call or result handling |
| Unsupported source shape or verifier crash | Keep the small reproducer and exact diagnostic; check the already working example |
| Proposed recursive JSON/parser/dictionary proof | Stop. You have crossed the intended dependency boundary |

**Do not spend hours extending a verifier to rescue this recipe.** If the accepted example works
but your small adaptation fails, identify the specific difference. If the necessary contract
cannot be represented, report that concrete gap. Do not call it a missing primitive merely
because an unrelated source shape was rejected, and do not claim it is supported without running
it. Verifier development requires separate explicit scope.

## Completion means evidence, not a written stub

- **Implemented:** production calls the adapter and classifies all outcomes.
- **Source accepted:** the named verifier actually passed for those files and contracts.
- **Behavior checked:** valid and invalid inputs exercise the intended success/error distinction.
- **Measured:** real attempts, including failures/retries, have retained timings and outcomes.
- **Composed:** the next task consumes the actual success and the larger DAG claim is proved.

Report these separately. Copying this recipe is the beginning of a small task check, not a
certificate for your application. Finish the current microclaim before starting the next one.
