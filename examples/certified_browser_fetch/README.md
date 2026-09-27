# Certified browser fetch

This minimal example contains a real JavaScript `fetch` round trip. Dagcert does not pretend to
prove the browser, HTTP, JSON, or Flask implementation. It proves the application-owned JavaScript
request decision, Python admission operation, and JavaScript response decision, then joins them
with two explicit `external_handoff` platform contracts.

The compiler-extracted edge types are `boolean -> bool` on the request and `bool -> boolean` on the
response. The contract names the exact JSON field at each crossing, adds each platform latency once,
and includes both engineering failure budgets in the composition's union bound. A URL-query handoff
supports `string -> str`; Dagcert deliberately refuses a generic query-string boolean conversion
because URL query values are strings unless application code defines and proves a codec.

Run:

```powershell
python -m examples.certified_browser_fetch.certify C:\proof-tools\maledictus.exe
```
