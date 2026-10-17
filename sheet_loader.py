"""Google Sheets loading via service account (preferred) or public CSV export."""

from __future__ import annotations

import io
import re
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

# Synthetic URL used only in unit tests for parse_sheet_url — not an app default.
EXAMPLE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "EXAMPLE_SPREADSHEET_ID_REPLACE_ME/"
    "edit?pli=1&gid=792137116#gid=792137116"
)

GOOGLE_API_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)

# Hints for both Shopee income exports and the RD Collectio ledger tab.
HEADER_HINTS = (
    "nama produk",
    "total penghasilan",
    "no. pesanan",
    "lihat berdasarkan",
    "money received date",
    "payment date",
    "qty sold",
    "variant",
    "income",
)

SECRETS_HINT = (
    "Set Streamlit secrets: gcp_service_account (JSON key fields), SHEET_ID, "
    "and optional SHEET_GID. Share the spreadsheet with the service account "
    "client_email as Viewer. Enable Google Sheets API and Google Drive API "
    "on the GCP project. Or paste a sheet URL in the sidebar for local testing."
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


def _as_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): value[k] for k in value.keys()}
    return dict(value)


def normalize_service_account_info(info: Mapping[str, Any]) -> dict[str, Any]:
    """Copy SA JSON fields; fix escaped newlines in private_key."""
    out = _as_plain_dict(info)
    key = out.get("private_key")
    if isinstance(key, str) and "\\n" in key and "\n" not in key:
        out["private_key"] = key.replace("\\n", "\n")
    return out


def secrets_get(secrets: Any, *keys: str, default: Any = None) -> Any:
    """Read the first present key from a Streamlit-like secrets mapping."""
    for key in keys:
        try:
            if key in secrets:
                return secrets[key]
        except Exception:  # noqa: BLE001 — secrets backends differ
            pass
        try:
            return secrets[key]
        except Exception:  # noqa: BLE001
            continue
    return default


def resolve_sheet_identity(
    secrets: Any = None,
    sidebar_url: str = "",
) -> tuple[Optional[str], Optional[str], Optional[dict[str, Any]], str]:
    """Resolve sheet id, gid, optional SA info, and load mode label.

    Priority:
    1. Sidebar URL override (id/gid) when non-empty — still uses SA when present.
    2. Secrets SHEET_ID / SHEET_GID / SHEET_URL.
    Returns (sheet_id, gid, service_account_info|None, source_label).
    """
    sa_raw = secrets_get(secrets, "gcp_service_account") if secrets is not None else None
    sa_info: Optional[dict[str, Any]] = None
    if sa_raw:
        sa_info = normalize_service_account_info(sa_raw)
        if not sa_info.get("client_email") or not sa_info.get("private_key"):
            sa_info = None

    sidebar_url = (sidebar_url or "").strip()
    if sidebar_url:
        sheet_id, gid = parse_sheet_url(sidebar_url)
        return sheet_id, gid, sa_info, "sidebar_url"

    sheet_id = secrets_get(secrets, "SHEET_ID", "sheet_id")
    gid = secrets_get(secrets, "SHEET_GID", "sheet_gid")
    secret_url = secrets_get(secrets, "SHEET_URL", "sheet_url")

    if sheet_id:
        sheet_id = str(sheet_id).strip()
        gid_out = str(gid).strip() if gid is not None and str(gid).strip() != "" else None
        return sheet_id, gid_out, sa_info, "secrets"

    if secret_url:
        sheet_id, url_gid = parse_sheet_url(str(secret_url))
        gid_out = str(gid).strip() if gid is not None and str(gid).strip() != "" else url_gid
        return sheet_id, gid_out, sa_info, "secrets_url"

    return None, None, sa_info, "none"


def _worksheet_by_gid(spreadsheet: Any, gid: Optional[str]) -> Any:
    if gid is None or str(gid).strip() == "":
        return spreadsheet.sheet1
    gid_str = str(gid).strip()
    for worksheet in spreadsheet.worksheets():
        if str(worksheet.id) == gid_str:
            return worksheet
    raise ValueError(
        f"No worksheet with gid={gid_str} in this spreadsheet. "
        "Check SHEET_GID / the gid in the sheet URL."
    )


def fetch_sheet_via_service_account(
    sheet_id: str,
    service_account_info: Mapping[str, Any],
    gid: Optional[str] = None,
) -> pd.DataFrame:
    """Load a private spreadsheet with gspread + google-auth."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:  # pragma: no cover
        raise ValueError(
            "Missing packages for private sheet access. "
            "Install requirements.txt (gspread, google-auth)."
        ) from exc

    info = normalize_service_account_info(service_account_info)
    email = info.get("client_email", "(unknown service account)")
    creds = Credentials.from_service_account_info(info, scopes=list(GOOGLE_API_SCOPES))
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(sheet_id)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"Could not open spreadsheet via service account ({email}). "
            "Share the sheet with that email as Viewer, confirm SHEET_ID, "
            "and enable Google Sheets API + Google Drive API on the GCP project. "
            f"Details: {exc}"
        ) from exc

    try:
        worksheet = _worksheet_by_gid(spreadsheet, gid)
        values = worksheet.get_all_values()
    except Exception as exc:  # noqa: BLE001
        if "gid=" in str(exc):
            raise
        raise ValueError(
            f"Could not read worksheet data via service account ({email}). "
            "Confirm SHEET_GID and that Drive API is enabled. "
            f"Details: {exc}"
        ) from exc

    if not values:
        return pd.DataFrame()
    raw = pd.DataFrame(values)
    return finalize_sheet_dataframe(raw)


def fetch_sheet_csv(
    url: str = "",
    timeout: int = 30,
    cache_bust: Optional[str] = None,
    sheet_id: Optional[str] = None,
    gid: Optional[str] = None,
) -> pd.DataFrame:
    """Public CSV export fallback (Anyone-with-the-link)."""
    if not sheet_id:
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
            "Google returned HTML instead of CSV (sheet is likely private). "
            + SECRETS_HINT
        )
    raw = pd.read_csv(io.BytesIO(content), header=None, dtype=str)
    return finalize_sheet_dataframe(raw)


def fetch_sheet(
    *,
    sheet_id: Optional[str] = None,
    gid: Optional[str] = None,
    url: str = "",
    service_account_info: Optional[Mapping[str, Any]] = None,
    timeout: int = 30,
    cache_bust: Optional[str] = None,
) -> pd.DataFrame:
    """Load sheet data: service account API first, else public CSV export."""
    if not sheet_id and url:
        sheet_id, parsed_gid = parse_sheet_url(url)
        if gid is None:
            gid = parsed_gid

    if not sheet_id:
        raise ValueError(SECRETS_HINT)

    if service_account_info:
        return fetch_sheet_via_service_account(
            sheet_id=sheet_id,
            service_account_info=service_account_info,
            gid=gid,
        )

    if url or sheet_id:
        return fetch_sheet_csv(
            url=url,
            sheet_id=sheet_id,
            gid=gid,
            timeout=timeout,
            cache_bust=cache_bust,
        )

    raise ValueError(SECRETS_HINT)
