"""Convert heterogeneous tool results into table-safe values for the Streamlit UI."""
from __future__ import annotations

import json
from typing import Any


def display_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize nested extraction context without modifying the underlying evidence.

    Pandas/Arrow cannot reliably infer a single scalar type from a column mixing
    PDF text strings and Excel worksheet dictionaries. Keep original rows intact
    for source verification and convert only their display copies.
    """
    return [
        {
            key: json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, (dict, list, tuple)) else value
            for key, value in row.items()
        }
        for row in rows
    ]
