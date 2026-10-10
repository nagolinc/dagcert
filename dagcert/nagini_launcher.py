"""Configure the pinned Nagini generator from its own compiler-extracted unions.

Upstream Nagini 1.3.1 generates normal union declarations/axioms only through
UNION_TYPE_SIZE=4 even when its compiler accepts a larger outcome union. Observe
the compiler's actual UnionType construction and size that existing generator
accordingly. No types, axioms, source bodies, proof obligations, or verifier
results are replaced, and the normal Viper dependency pruning is unchanged.
"""

from __future__ import annotations

from importlib import import_module
import sys


MARKER = "DAGCERT_NAGINI_UNION_ARITY="


def main() -> None:
    nodes = import_module("nagini_translation.lib.program_nodes")
    factory_module = import_module("nagini_translation.translators.type_domain_factory")
    union_type = nodes.UnionType
    factory = factory_module.TypeDomainFactory
    original_initializer = union_type.__init__
    original_size: int = factory.UNION_TYPE_SIZE
    if not isinstance(original_size, int) or original_size < 1:
        raise RuntimeError("pinned Nagini union generator configuration changed unexpectedly")

    def observe_union(instance: object, arguments: list[object]) -> None:
        original_initializer(instance, arguments)
        factory.UNION_TYPE_SIZE = max(factory.UNION_TYPE_SIZE, len(arguments))

    union_type.__init__ = observe_union
    try:
        result = import_module("nagini_translation.main").main()
        if result is not None:
            sys.exit(result)
    finally:
        # Report actual compiler configuration even for a failed proof. Dagcert
        # accepts it only alongside the real backend's successful proof result.
        print(f"{MARKER}{factory.UNION_TYPE_SIZE}", flush=True)


if __name__ == "__main__":
    main()
