from pathlib import Path
from shutil import copytree

from examples.certified_external_url.certify import main


def test_external_reference_example(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "examples" / "certified_external_url"
    copied = tmp_path / "certified_external_url"
    copytree(source, copied, ignore=lambda _path, names: {"artifacts"} & set(names))
    assert main(copied) == 0
