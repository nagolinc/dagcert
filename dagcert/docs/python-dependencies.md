# Python dependency identity is an issuance and verification gate

Hashing `requirements.txt` does not show that Python actually used those packages.
Dagcert checks that consistency automatically before running source proofs and again
before completing issuance or verification. Do not fix a mismatch with `PYTHONPATH`;
install the declared packages into the interpreter running the application and Dagcert.

The gate discovers a root `requirements*.txt` file or static `project.dependencies`
in `pyproject.toml`. If several declarations exist, select the intended environment
explicitly. An empty selection cannot bypass discovered dependency declarations.

```python
issue_certificate(
    contract, evidence, output,
    requirements_path=english_claims,
    source_root=app_root,
    python_requirements=("requirements-tv.txt",),
    proof_backend=backend,
)
```

The CLI equivalent is `--python-requirements requirements-tv.txt` on `issue`.
Verification reuses the certificate's recorded selection, or accepts the same explicit
argument. Selected files and recursively included `-r` files must be inside the
certified source manifest; ignoring a dependency file is refused.

The gate checks:

- Installed versions satisfy every applicable requirement, including transitive
  requirements, extras and environment markers.
- Git URL requirements name a full immutable commit, and installed PEP 610 provenance
  matches the repository, commit and optional subdirectory. Equal version strings do
  not excuse a different commit. Editable installations are refused.
- Installed runtime files match their wheel RECORD hashes. Their actual byte identity
  and installed version/provenance are bound in the certificate.
- Fresh import resolution and already-loaded modules belong to the recorded installed
  files. A checkout substituted through `PYTHONPATH`, a source-root shadow, or a stale
  module retained in `sys.modules` causes refusal.

The binding is in `source_verification.python_dependencies`. Verification rejects a
changed environment or a missing binding even if someone recomputes the certificate's
outer digest. The checking implementation is itself in the sealed verifier kernel.
Unsupported requirement syntax or mutable URL references fail with an explicit error;
Dagcert does not silently approximate installer behavior. Use ordinary PEP 508
requirements or static project dependencies and immutable Git URLs.

Scope: this establishes consistency of declared requirements, installer metadata,
installed bytes and imports in the interpreter doing certification. It trusts installer
metadata; it is not remote supply-chain attestation or a proof of dependency internals.
Deployments must verify in their actual runtime environment. A project with no Python
dependency declaration acquires no dependency-environment claim. Exact reproducibility
of future installs still requires appropriately pinned transitive requirements; the
certificate records the exact environment that was checked, including range resolutions.
