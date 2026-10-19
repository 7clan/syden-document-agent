"""Manage local indexed documents without following links or deleting other files."""
from __future__ import annotations

from pathlib import Path

from .ingest import SUPPORTED, _discover


def folder_files(folder: str | Path) -> list[str]:
    """List supported regular files under one active folder, including subfolders."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        return []
    return [str(path.relative_to(root)) for path in _discover(root)
            if path.suffix.lower() in SUPPORTED]


def remove_document(folder: str | Path, relative_name: str, *,
                    delete_permanently: bool = False) -> Path | None:
    """Remove a selected document from the indexed directory.

    Default moves a document to a sibling archive outside the indexed tree;
    permanent deletion requires the caller's explicit confirmation.
    Filenames are strictly relative and must resolve inside the chosen folder.
    """
    root = Path(folder).expanduser().resolve()
    relative = Path(relative_name)
    if (not relative_name or relative.is_absolute()
            or any(part in ("", ".", "..") for part in relative.parts)
            or relative.suffix.lower() not in SUPPORTED
            or not root.is_dir()):
        raise ValueError("Select a supported document within the current folder.")
    source = root / relative
    # Windows link/junction checks must apply to every path component.
    if any(p.is_symlink() for p in (source, *source.parents) if p != root):
        raise ValueError("Linked files and directories cannot be managed.")
    if not source.is_file() or not source.resolve().is_relative_to(root):
        raise ValueError("The selected document is no longer in this folder.")
    if delete_permanently:
        source.unlink()
        return None

    # Keep removed files beside (not inside) the indexed folder.
    archive = root.parent / f"{root.name}_removed"
    destination = archive / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 1001):
        new_path = (destination if attempt == 1 else
                    destination.with_name(f"{destination.stem} ({attempt})"
                                          f"{destination.suffix}"))
        if new_path.exists():
            continue
        source.rename(new_path)
        return new_path
    raise ValueError("Too many removed files have the same name.")
