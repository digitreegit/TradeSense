"""
Aggregate compliance JSONL (realized trades + wash-sale candidates) into one CSV.

For CPA / spreadsheet review only — not a substitute for broker 1099-B or tax software.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List

_TRADES_RE = re.compile(r"^trades-(\d{4}-\d{2}-\d{2})\.jsonl$")
_WASH_RE = re.compile(r"^wash-sales-(\d{4}-\d{2}-\d{2})\.jsonl$")

CSV_FIELDS = [
    "row_type",
    "time_iso",
    "symbol",
    "qty",
    "proceeds",
    "cost_basis",
    "gain_loss",
    "hold_term",
    "fifo_slices",
    "lot_id",
    "bought_on",
    "disposal_date",
    "wash_window_end",
    "realized_loss",
    "note",
]


def _iter_trades_for_year(log_dir: Path, year: int) -> Iterator[Dict[str, Any]]:
    for path in sorted(log_dir.glob("trades-*.jsonl")):
        m = _TRADES_RE.match(path.name)
        if not m:
            continue
        file_date = datetime.fromisoformat(m.group(1)).date()
        if file_date.year != year:
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield rec


def _iter_wash_for_year(log_dir: Path, year: int) -> Iterator[Dict[str, Any]]:
    for path in sorted(log_dir.glob("wash-sales-*.jsonl")):
        m = _WASH_RE.match(path.name)
        if not m:
            continue
        file_date = datetime.fromisoformat(m.group(1)).date()
        if file_date.year != year:
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                dd = rec.get("disposal_date")
                if isinstance(dd, str) and len(dd) >= 10:
                    try:
                        if datetime.fromisoformat(dd[:10]).date().year != year:
                            continue
                    except ValueError:
                        pass
                yield rec


def build_tax_csv_for_year(log_dir: Path, year: int, *, utf8_bom: bool = True) -> str:
    realized: List[Dict[str, Any]] = list(_iter_trades_for_year(log_dir, year))
    realized.sort(key=lambda r: str(r.get("time") or ""))

    wash: List[Dict[str, Any]] = list(_iter_wash_for_year(log_dir, year))
    wash.sort(
        key=lambda r: (
            str(r.get("disposal_date") or ""),
            str(r.get("lot_id") or ""),
        )
    )

    buf = io.StringIO()
    if utf8_bom:
        buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()

    for rec in realized:
        writer.writerow(
            {
                "row_type": "REALIZED",
                "time_iso": rec.get("time", ""),
                "symbol": rec.get("symbol", ""),
                "qty": rec.get("qty", ""),
                "proceeds": rec.get("proceeds", ""),
                "cost_basis": rec.get("cost_basis", ""),
                "gain_loss": rec.get("pnl", ""),
                "hold_term": rec.get("hold_term", ""),
                "fifo_slices": rec.get("fifo_slices", ""),
                "lot_id": "",
                "bought_on": "",
                "disposal_date": "",
                "wash_window_end": "",
                "realized_loss": "",
                "note": "",
            }
        )

    for rec in wash:
        writer.writerow(
            {
                "row_type": "WASH_CANDIDATE",
                "time_iso": "",
                "symbol": rec.get("symbol", ""),
                "qty": rec.get("qty", ""),
                "proceeds": rec.get("proceeds", ""),
                "cost_basis": rec.get("cost_basis", ""),
                "gain_loss": "",
                "hold_term": "",
                "fifo_slices": "",
                "lot_id": rec.get("lot_id", ""),
                "bought_on": rec.get("bought_on", ""),
                "disposal_date": rec.get("disposal_date", ""),
                "wash_window_end": rec.get("wash_window_end", ""),
                "realized_loss": rec.get("realized_loss", ""),
                "note": rec.get("note", ""),
            }
        )

    return buf.getvalue()
