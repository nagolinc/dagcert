# Certified alternative producers

This minimal example has two real reservation operations that can independently feed one request
builder. The two typed edges share `alternative_group: "request-source"`, so either producer makes
the builder reachable. They are not simultaneous prerequisites.

Run `python -m examples.certified_alternative_producers.certify` from the repository root to issue
and independently verify the v14 certificate.
