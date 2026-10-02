"""CSV exports that keep supplier and customer text as spreadsheet text cells."""

from __future__ import annotations

import pandas as pd


def csv_export_bytes(rows: list[dict] | pd.DataFrame) -> bytes:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)

    def text_cell(value):
        if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    frame = frame.map(text_cell)
    frame.columns = [text_cell(str(column)) for column in frame.columns]
    return frame.to_csv(index=False).encode("utf-8-sig")
