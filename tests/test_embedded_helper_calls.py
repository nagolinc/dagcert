"""Effects belong to real callers in a worker's sealed helper closure."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from dagcert.certificate import CertificateError, maledictus_embedded_external_calls
from dagcert.contract import Contract, EmbeddedExternalBoundary, ExternalProvider, Implementation, Task
from dagcert.maledictus_verifier import (
    MaledictusEmbeddedExternalCall, MaledictusVerificationError, verify_with_maledictus,
)
from dagcert.source_types import SourceSignature


def fixture(root: Path) -> tuple[Contract, list[str]]:
    sources = {
        'worker.py': 'from helper import invoke\nfrom adapter import emit\ndef run():\n    invoke()\n    emit()\n',
        'helper.py': 'from adapter import emit\ndef invoke():\n    emit()\n',
        'adapter.py': 'def emit():\n    pass\n',
    }
    for path, source in sources.items():
        (root / path).write_text(source, encoding='utf-8')
    signature = SourceSignature('python', 'worker.py', 'run', 'Input', ('Output',), 3)
    task = Task('work', 'worker', 'Input', 'Output',
                implementation=Implementation('python', 'worker.py', 'run'),
                source_signature=signature, external_calls=('emit',))
    boundary = EmbeddedExternalBoundary(
        'emit', Implementation('python', 'adapter.py', 'emit'), 'native_contract.py',
        'Native provider premise', ExternalProvider('native', ('emit',)),
        'declared-by-exsures', replace(signature, path='adapter.py', symbol='emit'),
    )
    return Contract('dagcert-contract/v12', (), (task,), (), external_boundaries=(boundary,)), list(sources)


def test_helper_and_root_consumers_share_one_task(tmp_path: Path) -> None:
    contract, manifest = fixture(tmp_path)
    calls = maledictus_embedded_external_calls(contract, tmp_path, source_manifest_paths=manifest)
    assert calls == (
        MaledictusEmbeddedExternalCall('helper.py', 'invoke', 'emit', 'adapter.py', 'emit'),
        MaledictusEmbeddedExternalCall('worker.py', 'run', 'emit', 'adapter.py', 'emit'),
    )
    assert len(contract.tasks) == 1


def test_common_consumer_is_sealed_once_across_tasks(tmp_path: Path) -> None:
    contract, manifest = fixture(tmp_path)
    contract = replace(contract, tasks=(*contract.tasks, replace(contract.tasks[0], id='other')))
    calls = maledictus_embedded_external_calls(contract, tmp_path, source_manifest_paths=manifest)
    assert len(calls) == 2
    assert len(contract.tasks) == 2


def test_manifest_exclusion_cannot_hide_helper_effect(tmp_path: Path) -> None:
    contract, manifest = fixture(tmp_path)
    manifest.remove('helper.py')
    with pytest.raises(CertificateError, match='outside the exact manifest'):
        maledictus_embedded_external_calls(contract, tmp_path, source_manifest_paths=manifest)


def test_unused_function_does_not_satisfy_declared_effect(tmp_path: Path) -> None:
    contract, manifest = fixture(tmp_path)
    (tmp_path / 'worker.py').write_text(
        'from adapter import emit\ndef run():\n    def unused():\n        emit()\n', encoding='utf-8')
    with pytest.raises(CertificateError, match='not reachable'):
        maledictus_embedded_external_calls(contract, tmp_path, source_manifest_paths=manifest)


def test_helper_symbols_are_requested_without_adding_operation_root(tmp_path: Path, monkeypatch) -> None:
    fixture(tmp_path)
    executable = tmp_path / 'verifier.exe'
    executable.write_bytes(b'pinned verifier fixture')
    captured = {}

    def fake_run(arguments, **_kwargs):
        captured.update(json.loads(Path(arguments[-1]).read_text(encoding='utf-8')))
        return CompletedProcess(arguments, 1, '', 'intentional test refusal')

    monkeypatch.setattr('dagcert.maledictus_verifier.run', fake_run)
    with pytest.raises(MaledictusVerificationError, match='intentional test refusal'):
        verify_with_maledictus(
            tmp_path, ['worker.py'], {'worker.py': ('run',)},
            source_fingerprint='fixture', executable=executable,
            expected_executable_sha256=sha256(executable.read_bytes()).hexdigest(),
            proof_only_files=('helper.py', 'adapter.py'),
            embedded_external_calls=(
                MaledictusEmbeddedExternalCall('helper.py', 'invoke', 'emit', 'adapter.py', 'emit'),
            ),
        )
    assert captured['files'] == [
        {'path': 'adapter.py', 'language': 'python', 'symbols': []},
        {'path': 'helper.py', 'language': 'python', 'symbols': ['invoke']},
        {'path': 'worker.py', 'language': 'python', 'symbols': ['run']},
    ]


def test_embedded_consumer_cannot_add_an_unsealed_file(tmp_path: Path) -> None:
    fixture(tmp_path)
    executable = tmp_path / 'verifier.exe'
    executable.write_bytes(b'pinned verifier fixture')
    with pytest.raises(MaledictusVerificationError, match='outside the sealed source closure'):
        verify_with_maledictus(
            tmp_path, ['worker.py'], {'worker.py': ('run',)},
            source_fingerprint='fixture', executable=executable,
            expected_executable_sha256=sha256(executable.read_bytes()).hexdigest(),
            embedded_external_calls=(
                MaledictusEmbeddedExternalCall('helper.py', 'invoke', 'emit', 'adapter.py', 'emit'),
            ),
        )
