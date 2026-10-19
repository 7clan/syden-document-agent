"""Safely copy files selected in the browser into the active document folder."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .ingest import SUPPORTED

_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_NAMES = re.compile(
    r"(?i)^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$"
)


def save_uploaded_file(folder: str | Path, filename: str,
                       content: bytes | memoryview, max_bytes: int,
                       *, replace_existing: bool = False) -> str:
    """Save a document; replace an exact filename only with explicit approval.

    The default safely renames duplicates, e.g. 'Contract (2).pdf'. A confirmed
    replacement uses a temporary file and atomic rename, so a write failure
    cannot corrupt the existing file. The caller must re-index after saving.
    """
    if (not filename or filename != filename.strip()
            or len(filename) > 180 or filename.startswith(".")
            or filename.endswith(".") or _INVALID_NAME.search(filename)
            or _RESERVED_WINDOWS_NAMES.fullmatch(filename)):
        raise ValueError("Invalid filename. Select a normal PDF, Excel, or Word file.")

    original = Path(filename)
    if original.suffix.lower() not in SUPPORTED:
        raise ValueError("Unsupported file type. Choose PDF, Excel, or Word (.docx).")
    if len(content) == 0:
        raise ValueError("Empty file cannot be indexed.")
    if len(content) > max_bytes:
        raise ValueError(f"File exceeds the configured {max_bytes // 1024 // 1024} MiB limit.")

    destination = Path(folder).expanduser().resolve()
    if replace_existing:
        target = destination / filename
        if not target.is_file():
            raise ValueError("Replacement target not found; file was not saved.")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="wb", dir=destination, prefix=".syden-update-",
                    suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            # The exact extension/name is preserved; never select by basename.
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return filename

    destination.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 1001):
        name = (filename if attempt == 1 else
                f"{original.stem} ({attempt}){original.suffix}")
        path = destination / name
        try:
            with path.open("xb") as handle:
                handle.write(content)
        except FileExistsError:
            continue
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return name
    raise ValueError("Too many documents with this filename.")
