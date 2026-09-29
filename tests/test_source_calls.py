from pathlib import Path

import pytest

from dagcert.proof_sources import ProofSourceError
from dagcert.source_calls import PythonSourceCall, resolve_python_source_calls


def write_sources(root: Path, sources: dict[str, str]) -> list[str]:
    for name, text in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return list(sources)


def test_local_helpers_and_multiple_consumers_are_preserved(tmp_path: Path) -> None:
    manifest = write_sources(tmp_path, {
        'worker.py': 'from native import adapter\ndef helper():\n    adapter()\ndef run():\n    helper()\n    adapter()\n',
        'native.py': 'def adapter():\n    pass\n',
    })
    assert resolve_python_source_calls(tmp_path, [('worker.py', 'run')], manifest) == (
        PythonSourceCall('worker.py', 'helper', 'native.py', 'adapter'),
        PythonSourceCall('worker.py', 'run', 'native.py', 'adapter'),
        PythonSourceCall('worker.py', 'run', 'worker.py', 'helper'),
    )


def test_relative_reexports_and_module_aliases(tmp_path: Path) -> None:
    manifest = write_sources(tmp_path, {
        'pkg/__init__.py': 'from .helper import invoke as exported\n',
        'pkg/helper.py': 'import native as api\ndef invoke():\n    api.adapter()\n',
        'worker.py': 'from pkg import exported as call\ndef run():\n    call()\n',
        'native.py': 'def adapter():\n    pass\n',
    })
    assert resolve_python_source_calls(tmp_path, [('worker.py', 'run')], manifest) == (
        PythonSourceCall('pkg/helper.py', 'invoke', 'native.py', 'adapter'),
        PythonSourceCall('worker.py', 'run', 'pkg/helper.py', 'invoke'),
    )


def test_recursive_helpers_terminate_without_inventing_nested_calls(tmp_path: Path) -> None:
    manifest = write_sources(tmp_path, {
        'worker.py': 'from native import adapter\ndef run():\n    def unused():\n        adapter()\n    deferred = lambda: adapter()\n    run()\n',
        'native.py': 'def adapter():\n    pass\n',
    })
    assert resolve_python_source_calls(tmp_path, [('worker.py', 'run')], manifest) == (
        PythonSourceCall('worker.py', 'run', 'worker.py', 'run'),
    )


@pytest.mark.parametrize('body', [
    'def run(adapter):\n    adapter()\n',
    'def run():\n    adapter = replacement\n    adapter()\n',
    'def run():\n    def adapter():\n        pass\n    adapter()\n',
    'def run():\n    try:\n        pass\n    except Exception as adapter:\n        adapter()\n',
])
def test_shadowed_import_never_acquires_source_target(tmp_path: Path, body: str) -> None:
    manifest = write_sources(tmp_path, {
        'worker.py': 'from native import adapter\n' + body,
        'native.py': 'def adapter():\n    pass\n',
    })
    with pytest.raises(ProofSourceError, match='shadowed source call'):
        resolve_python_source_calls(tmp_path, [('worker.py', 'run')], manifest)


def test_unsealed_helper_is_refused(tmp_path: Path) -> None:
    write_sources(tmp_path, {
        'worker.py': 'from helper import call\ndef run():\n    call()\n',
        'helper.py': 'def call():\n    pass\n',
    })
    with pytest.raises(ProofSourceError, match='outside the exact manifest'):
        resolve_python_source_calls(tmp_path, [('worker.py', 'run')], ['worker.py'])


def test_rebound_module_function_is_refused(tmp_path: Path) -> None:
    manifest = write_sources(tmp_path, {
        'worker.py': 'def helper():\n    pass\nhelper = replacement\ndef run():\n    helper()\n',
    })
    with pytest.raises(ProofSourceError, match='rebound source call'):
        resolve_python_source_calls(tmp_path, [('worker.py', 'run')], manifest)


def test_ambiguous_provider_module_is_refused(tmp_path: Path) -> None:
    manifest = write_sources(tmp_path, {
        'worker.py': 'from helper import call\ndef run():\n    call()\n',
        'helper.py': 'def call():\n    pass\n',
        'helper/__init__.py': 'def call():\n    pass\n',
    })
    with pytest.raises(ProofSourceError, match='ambiguous application call module'):
        resolve_python_source_calls(tmp_path, [('worker.py', 'run')], manifest)
