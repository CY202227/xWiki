"""Distribution audit rejects sensitive and unexpected package contents."""
import zipfile

import pytest

from scripts.check_distributions import check_artifact


@pytest.mark.parametrize("extra", [".env.test.local", "data/source.md", "tests/test_secret.py", "xwiki/private.sqlite"])
def test_distribution_audit_rejects_private_or_unexpected_files(tmp_path, extra):
    path = tmp_path / "xwiki.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name in ["xwiki/__init__.py", "xwiki/__main__.py", "xwiki/service.py", "xwiki/evidence.py", extra]:
            archive.writestr(name, "synthetic")
    with pytest.raises(ValueError):
        check_artifact(path)
