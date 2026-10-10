"""Audit distribution contents without extracting archives or reading secrets."""
import argparse
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def check_artifact(path: Path) -> dict:
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        wheel = True
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            names = [item.name for item in archive.getmembers() if item.isfile()]
        names = [name.partition("/")[2] for name in names]
        wheel = False
    else:
        raise ValueError("Expected a wheel or source archive")
    required = {"xwiki/__init__.py", "xwiki/__main__.py", "xwiki/service.py", "xwiki/evidence.py"}
    if not required <= set(names):
        raise ValueError(f"{path.name}: missing required package modules")
    for name in names:
        parts = PurePosixPath(name).parts
        if any(part.startswith(".env") or part in {"data", "__pycache__", ".git", ".venv"} for part in parts):
            raise ValueError(f"{path.name}: private/runtime file in distribution")
        if name.endswith((".pyc", ".sqlite", ".db")) or ".." in parts or name.startswith("/"):
            raise ValueError(f"{path.name}: unexpected runtime or unsafe file")
        if wheel and parts[0] != "xwiki" and not parts[0].endswith(".dist-info"):
            raise ValueError(f"{path.name}: unexpected top-level wheel content")
    if not wheel and not {"pyproject.toml", "tests/fixtures/wiki_eval.json", "scripts/evaluate_wiki.py",
                          "scripts/demo_wiki.py", "examples/garden/README.md",
                          "examples/garden/sources/01-rain.md", "examples/garden/sources/02-compost.md",
                          "examples/garden/sources/03-rain-update.md"} <= set(names):
        raise ValueError(f"{path.name}: source archive missing reproducibility files")
    return {"artifact": path.name, "files": len(names), "ok": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="dist")
    args = parser.parse_args()
    folder = Path(args.directory)
    artifacts = sorted([*folder.glob("*.whl"), *folder.glob("*.tar.gz")])
    if not artifacts:
        raise SystemExit("No distributions found")
    print(json.dumps([check_artifact(path) for path in artifacts]))


if __name__ == "__main__":
    main()
