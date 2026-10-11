# Structured LLM output: copy this boundary

Read `dagcert --help structuredLLMOutput` (also `dagcert help structuredLLMOutput`) for the complete
recipe. The [packaged guide](../../dagcert/docs/structured-llm-output.md) shows every source and
contract connection, success/failure accounting, adaptation steps, and the stop rule.

This runnable example accepts an LLM response only when a real schema validator accepts it.
It starts with response text, so checking it requires no credentials, model request, or browser.
The schema requires string `title` and `summary` fields and allows extra metadata. The successful
result preserves the exact text. Invalid JSON, wrong types, missing fields, and provider errors
produce `PlanFailed`. The consumer schema is deliberately small, with no arbitrary limits.

```text
python -m pip install -e ".[structured-output]"
python -m examples.structured_llm_output.verify PATH_TO_MALEDICTUS
python -m pytest tests/test_structured_llm_output.py
```

Use your configured Maledictus runtime. The source check pins the executable digest and writes
`.cache/structured-llm-output/source-proof.json`. It runs through Dagcert's public source checker,
including strict mypy, the real adapter body, native provider overlay, and task-to-adapter binding.
The example was accepted with executable SHA-256
`0b66dba6d95f5191fab09762bc902e0dc852d85b55622fc1555e1621f2634c40` and pydantic-core `2.50.1`.

This is a type/exception-closure source proof under an explicit schema-validator assumption,
plus behavior tests. It is not a proof of the validator's internals, a live LLM measurement,
or an issued application certificate. In production, put the real model call before validation,
handle its failure, and measure the entire task including all attempts.

`ExternalSuccess(False)` is a successful **typed adapter return** but a **failed task**. Only
`PlanReady` receives useful-output credit. This distinction is intentional and tested.
