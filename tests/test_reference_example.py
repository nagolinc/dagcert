from pathlib import Path
from shutil import copytree

from examples.certified_vote.certify import main


def test_reference_example(tmp_path: Path):
    source = Path(__file__).parents[1] / "examples" / "certified_vote"
    copied = tmp_path / "certified_vote"
    copytree(source, copied, ignore=lambda _path, names: {"artifacts"} & set(names))
    assert main(copied) == 0
