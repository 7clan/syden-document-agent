"""Create a source-only submission ZIP; never include local secrets or documents."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "AGENTS.md", "PROMPT_FOR_CODEX.md", "pyproject.toml",
              "app.py", ".env.example", ".gitignore"}
SOURCE_DIRS = {"src": {".py"}, "tests": {".py"}, "scripts": {".py"},
               ".github": {".yml", ".yaml"}}
DOC_FILES = {"TEST_PLAN.md", "DEVELOPMENT_NOTE.md", "DEVELOPMENT_NOTE_TEMPLATE.md"}


def source_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    files.extend(ROOT / "docs" / name for name in DOC_FILES
                 if (ROOT / "docs" / name).is_file())
    for directory, suffixes in SOURCE_DIRS.items():
        base = ROOT / directory
        if not base.is_dir():
            continue
        files.extend(path for path in base.rglob("*")
                     if path.is_file() and not path.is_symlink()
                     and path.suffix.lower() in suffixes
                     and not any(part.startswith(".") or part.endswith(".egg-info")
                                 or part in {"__pycache__", "build", "dist"}
                                 for part in path.relative_to(base).parts))
    return sorted(set(files))


def package(destination: Path) -> Path:
    target = destination.resolve()
    if target == ROOT / ".env":
        raise ValueError("Refusing to overwrite .env")
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, path.relative_to(ROOT).as_posix())
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", default=".local/submission/syden-document-agent.zip")
    args = parser.parse_args()
    print(f"Created source-only archive: {package(Path(args.output))}")
