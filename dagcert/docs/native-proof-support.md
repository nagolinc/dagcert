# Carry component native contracts into certificate issuance

Use the structuredLLMOutput recipe for a new structured-output task. This page
covers an existing component that already has accepted Maledictus native
provider contracts and needs to pass through the public certificate issuer.

Supply those proof inputs to the same public source gate used by `issue_certificate`
and `verify_certificate`:

```python
backend = SourceProofBackend.maledictus(
    executable, executable_sha256,
    native_proof_support="proof-support.json",
    timeout_seconds=None,
)
```

The timeout controls the verifier process only. It is not an application timing
premise. Omitting it preserves the existing 120-second process timeout.

A `dagcert-native-proof-support/v1` document has exactly three fields:

```json
{
  "schema": "dagcert-native-proof-support/v1",
  "annotations": {
    "app/task.py": {"path": "task-annotations.py", "sha256": "EXACT_FILE_SHA256"}
  },
  "native_contracts": [
    {
      "boundary_id": "native.validation",
      "adapter_path": "app/task.py",
      "adapter_symbol": "build",
      "provider_module": "jsonschema",
      "provider_symbols": ["Draft202012Validator"],
      "exception_policy": "declared-by-exsures",
      "stub": {"path": "jsonschema_contract.py", "sha256": "EXACT_FILE_SHA256"},
      "assumption": "The installed validator implements the attached native contract."
    }
  ]
}
```

Paths to annotation and contract files resolve relative to this document.
Application paths resolve against the certified source root. More than one
native provider may be used by an operation or an ordinary checked helper.
The provider is resolved and its environment identity is included in the proof.
Application-owned modules cannot be relabeled native dependencies.

Annotation views must preserve the executable AST. They may add checked
postconditions, invariants and helper preconditions, and proof-only predicates
that executable code does not call. They cannot replace bodies, add unchecked
axioms, or restrict a closed operation with `Requires`. Dagcert retains any
additional relation obligations it generates itself. Maledictus reruns the
proof and its mandatory pinned, strict Python typechecker using the same native
interfaces. A host typeshed's unrelated `Any` return does not override the
explicit native type contract being checked.

Keep separate microclaims separate. If different accepted components use
different interfaces for a native library, use a bundle instead of merging them
into one universal library contract:

```json
{
  "schema": "dagcert-native-proof-bundle/v1",
  "components": [
    {
      "operations": [{"path": "app/task.py", "symbol": "build"}],
      "support": "build-support.json",
      "sha256": "EXACT_SUPPORT_DOCUMENT_SHA256"
    }
  ]
}
```

Each requested operation must have exactly one component. Components are leaves;
nested bundles are rejected. An optional `backend` object with `executable` and
`sha256` preserves an explicitly pinned component verifier. Those pins remain
visible trusted tool dependencies; no saved success flag replaces execution.

Issuance and independent verification both rerun each component. A subsequent
source-relation check proves only the relation's owners and their transitive
dependencies. Other operations already passed the initial source gate.

Component proof acceptance is not final certificate issuance. Derived timing,
source relations, translation coverage, evidence identity and independent
verification must still pass. In particular, observations do not establish
uniform future performance bounds; those engineering premises remain explicit.
