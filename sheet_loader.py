"""Google Sheets URL parsing and CSV loading for sales exports."""

from __future__ import annotations

import io
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1uInQ3r5p0ye8t5PqXEb5J7Jltwtxn1sZ8KB1vf8sr9o/"
    "edit?pli=1&gid=792137116#gid=792137116"
)

# Hints for both Shopee income exports and the RD Collectio ledger tab.
HEADER_HINTS = (
    "nama produk",
    "total penghasilan",
    "no. pesanan",
    "lihat berdasarkan",
    "money received date",
    "qty sold",
    "variant",
    "income",
)


def parse_sheet_url(url: str) -> tuple[str, Optional[str]]:
    """Extract spreadsheet id and optional gid from an edit/export URL."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Sheet URL is empty.")

    sheet_id_match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not sheet_id_match:
        raise ValueError("Could not find a Google Sheets document id in the URL.")

    sheet_id = sheet_id_match.group(1)
    gid: Optional[str] = None

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "gid" in qs and qs["gid"]:
        gid = qs["gid"][0]
    else:
        frag = parse_qs(parsed.fragment)
        if "gid" in frag and frag["gid"]:
            gid = frag["gid"][0]
        else:
            hash_match = re.search(r"gid=(\d+)", url)
            if hash_match:
                gid = hash_match.group(1)

    return sheet_id, gid


def csv_export_url(
    sheet_id: str,
    gid: Optional[str] = None,
    cache_bust: Optional[str] = None,
) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid is not None:
        base += f"&gid={gid}"
    if cache_bust:
        base += f"&_cb={cache_bust}"
    return base


def _normalize_col(name: object) -> str:
    text = str(name or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _find_header_row(raw: pd.DataFrame, max_scan: int = 20) -> int:
    for idx in range(min(max_scan, len(raw))):
        values = [_normalize_col(v) for v in raw.iloc[idx].tolist()]
        hits = sum(1 for hint in HEADER_HINTS if any(hint in v for v in values))
        if hits >= 2:
            return idx
    return 0


def finalize_sheet_dataframe(raw: pd.DataFrame) -> pd.DataFrame:
    """Promote the real header row and drop empty columns."""
    if raw.empty:
        return raw

    header_idx = _find_header_row(raw)
    headers = [
        str(v).strip() if str(v).strip() and str(v).strip().lower() != "nan" else f"col_{i}"
        for i, v in enumerate(raw.iloc[header_idx].tolist())
    ]
    # Deduplicate column names
    seen: dict[str, int] = {}
    unique_headers: list[str] = []
    for h in headers:
        if h in seen:
            seen[h] += 1
            unique_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            unique_headers.append(h)

    df = raw.iloc[header_idx + 1 :].copy()
    df.columns = unique_headers
    df = df.dropna(how="all")
    df = df.loc[:, ~df.columns.str.match(r"^col_\d+$") | df.notna().any()]
    return df.reset_index(drop=True)


def fetch_sheet_csv(
    url: str,
    timeout: int = 30,
    cache_bust: Optional[str] = None,
) -> pd.DataFrame:
    sheet_id, gid = parse_sheet_url(url)
    export = csv_export_url(sheet_id, gid, cache_bust=cache_bust)
    response = requests.get(
        export,
        timeout=timeout,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    response.raise_for_status()
    content = response.content
    if b"<!DOCTYPE html" in content[:200].lower() or b"<html" in content[:200].lower():
        raise ValueError(
            "Google returned HTML instead of CSV. Make sure the sheet is shared "
            "as 'Anyone with the link' can view."
        )
    raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str)
    return finalize_sheet_dataframe(raw)
