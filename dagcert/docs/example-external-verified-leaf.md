# Example: external verified leaf

An alternate proof backend is selected explicitly and pinned by executable SHA-256. The leaf is
bound to exact source and symbol identity; an application checker cannot substitute a boolean.

```powershell
dagcert lint dag_contract.json --requirements english_requirements.json `
  --proof-backend maledictus `
  --proof-backend-executable C:\proof-tools\maledictus.exe `
  --proof-backend-sha256 <64-hex-digest>
```

Application-owned TypeScript or JavaScript and an external platform are different boundaries.
The application leaf must be proved by a backend capability that covers its language, closed
outcomes, and exceptional exits. A browser or other platform call remains an explicit external
contract and assumption. Source digest changes, missing backend capabilities, or an outcome not in
the verified interface refuse issuance.

Do not treat `tsc --strict` alone as an exception/effect proof, and do not replace a browser stage
with a synthetic Python observer. The verified leaf must name the production source actually
executed by the application.

`examples/certified_typescript_leaf` is a complete v11 example. The contract's
`verified_interface` is checked against the interface extracted by pinned TypeScript 5.9.3; it is
not trusted as a hand-written type declaration.
