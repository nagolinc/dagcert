# Certified TypeScript leaf

This minimal example proves and composes two real TypeScript functions. Dagcert treats the
`verified_interface` objects as assertions only; Maledictus asks pinned TypeScript 5.9.3 for each
real source signature and refuses any mismatch. Maledictus also proves the accepted function bodies
have no undeclared exceptional exit in its advertised TypeScript fragment.

The 5 ms leaf timings are explicit premises, not benchmark results. A browser or other host remains
an environment boundary and must be stated as an assumption; it is not magically proved by checking
application TypeScript.

Run:

```powershell
python -m examples.certified_typescript_leaf.certify C:\proof-tools\maledictus.exe
```
