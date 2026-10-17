"""Lightweight checks for sheet parsing and BurnX metrics."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app import (
    DEFAULT_INITIAL_STOCK,
    INITIAL_STOCK_AS_OF,
    date_basis_options,
    default_date_range,
    filter_items,
    format_pcs_with_boxes,
    stock_ins_in_scope,
    stock_remaining,
)
from products import PCS_PER_BOX, build_line_items, demo_line_items, map_columns, _to_float
from sheet_loader import (
    EXAMPLE_SHEET_URL,
    normalize_service_account_info,
    parse_sheet_url,
    resolve_sheet_identity,
    secrets_get,
)

NEW_SHEET_ID = "EXAMPLE_SPREADSHEET_ID_REPLACE_ME"
NEW_GID = "792137116"


def test_parse_url() -> None:
    sheet_id, gid = parse_sheet_url(EXAMPLE_SHEET_URL)
    assert sheet_id == NEW_SHEET_ID
    assert gid == NEW_GID


def test_parse_url_with_pli() -> None:
    url = (
        f"https://docs.google.com/spreadsheets/d/{NEW_SHEET_ID}/"
        f"edit?pli=1&gid={NEW_GID}#gid={NEW_GID}"
    )
    sheet_id, gid = parse_sheet_url(url)
    assert sheet_id == NEW_SHEET_ID
    assert gid == NEW_GID


def test_resolve_sheet_identity_from_secrets() -> None:
    secrets = {
        "SHEET_ID": NEW_SHEET_ID,
        "SHEET_GID": NEW_GID,
        "gcp_service_account": {
            "client_email": "sa@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\\nABC\\n-----END PRIVATE KEY-----\\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }
    sheet_id, gid, sa, source = resolve_sheet_identity(secrets)
    assert sheet_id == NEW_SHEET_ID
    assert gid == NEW_GID
    assert source == "secrets"
    assert sa is not None
    assert "\n" in sa["private_key"]
    assert "\\n" not in sa["private_key"]

    # Sidebar URL overrides id/gid but keeps SA.
    override = (
        f"https://docs.google.com/spreadsheets/d/{NEW_SHEET_ID}/edit#gid=1"
    )
    sheet_id2, gid2, sa2, source2 = resolve_sheet_identity(secrets, sidebar_url=override)
    assert sheet_id2 == NEW_SHEET_ID
    assert gid2 == "1"
    assert source2 == "sidebar_url"
    assert sa2 is not None


def test_secrets_get_and_normalize_key() -> None:
    assert secrets_get({"SHEET_ID": "abc"}, "SHEET_ID", "sheet_id") == "abc"
    assert secrets_get({}, "SHEET_ID", default="x") == "x"
    info = normalize_service_account_info({"private_key": "A\\nB\\nC"})
    assert info["private_key"] == "A\nB\nC"


def test_idr_float() -> None:
    assert _to_float("IDR30,000") == 30_000
    assert _to_float("-IDR500,000") == -500_000


def test_stock_remaining() -> None:
    remain, raw, over = stock_remaining(100, 40)
    assert remain == 60 and raw == 60 and not over
    remain, raw, over = stock_remaining(10, 25)
    assert remain == 0 and raw == -15 and over


def test_stock_remaining_with_stock_in_simulation() -> None:
    # Lemon init 220 as of 23 Sep; sell 20 on 25 Sep; +300 on 30 Sep → 500.
    remain, raw, over = stock_remaining(220, 20, 300)
    assert remain == 500 and raw == 500 and not over
    assert INITIAL_STOCK_AS_OF == date(2026, 9, 23)
    assert DEFAULT_INITIAL_STOCK["stock_matcha_lemon"] == 220
    assert DEFAULT_INITIAL_STOCK["stock_matcha_mango"] == 200
    assert DEFAULT_INITIAL_STOCK["stock_fiber_strawberry"] == 270
    assert DEFAULT_INITIAL_STOCK["stock_fiber_raspberry"] == 240
    assert DEFAULT_INITIAL_STOCK["stock_fiber_blackcurrant"] == 185

    events = [
        {
            "product_line": "BurnX Matcha",
            "variant": "Lemon",
            "on_date": date(2026, 9, 30),
            "pcs": 300,
        },
        {
            "product_line": "BurnX Matcha",
            "variant": "Lemon",
            "on_date": date(2026, 9, 20),  # before From — ignored
            "pcs": 50,
        },
    ]
    scoped = stock_ins_in_scope(
        events,
        "BurnX Matcha",
        "Lemon",
        date(2026, 9, 23),
        date(2026, 10, 6),
    )
    assert scoped == 300
    # Outside applied To — ignored
    assert (
        stock_ins_in_scope(
            events,
            "BurnX Matcha",
            "Lemon",
            date(2026, 9, 23),
            date(2026, 9, 28),
        )
        == 0
    )


def test_format_pcs_with_boxes() -> None:
    assert format_pcs_with_boxes(27, "BurnX Fiber") == "27 pcs (1.5 box)"
    assert format_pcs_with_boxes(20, "BurnX Matcha") == "20 pcs (1.0 box)"
    assert PCS_PER_BOX["BurnX Fiber"] == 18
    assert PCS_PER_BOX["BurnX Matcha"] == 20


def test_demo_metrics() -> None:
    demo = demo_line_items()
    assert not demo.empty
    assert set(demo["product_line"]) <= {"BurnX Matcha", "BurnX Fiber"}
    assert (demo["net_revenue"] == demo["gross_revenue"] - demo["cogs"]).all()
    assert "payment_at" in demo.columns
    assert demo["payment_at"].notna().any()


def test_date_basis_options_always_both() -> None:
    # Even with empty / all-null payment_at, both labels stay selectable.
    empty = pd.DataFrame({"disbursed_at": [], "payment_at": []})
    sparse = pd.DataFrame(
        {"disbursed_at": [pd.Timestamp("2026-01-01")], "payment_at": [pd.NaT]}
    )
    assert date_basis_options(empty) == ["Disbursed Date", "Payment Date"]
    assert date_basis_options(sparse) == ["Disbursed Date", "Payment Date"]
    assert date_basis_options(None) == ["Disbursed Date", "Payment Date"]


def test_default_date_range_baseline() -> None:
    today = date(2026, 10, 6)
    start, end = default_date_range(today)
    assert start == INITIAL_STOCK_AS_OF == date(2026, 9, 23)
    assert end == today


def test_date_basis_filter() -> None:
    demo = demo_line_items()
    by_payment = filter_items(
        demo, ["BurnX Matcha"], date(2026, 8, 8), date(2026, 8, 11), date_column="payment_at"
    )
    by_disbursed = filter_items(
        demo, ["BurnX Matcha"], date(2026, 8, 8), date(2026, 8, 11), date_column="disbursed_at"
    )
    # Payment dates are earlier than disbursed on demo rows — sets differ.
    assert not by_payment.empty
    assert not by_disbursed.empty
    assert float(by_payment["pcs"].sum()) != float(by_disbursed["pcs"].sum())


def test_live_sheet_optional() -> None:
    """Optional live fetch via local secrets — skipped when unavailable."""
    from pathlib import Path

    from sheet_loader import fetch_sheet

    secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print("skip live sheet: no .streamlit/secrets.toml")
        return

    try:
        import tomllib
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    with secrets_path.open("rb") as fh:
        secrets = tomllib.load(fh)

    sheet_id, gid, sa, _source = resolve_sheet_identity(secrets)
    if not sheet_id or not sa:
        print("skip live sheet: secrets missing SHEET_ID or gcp_service_account")
        return

    try:
        raw = fetch_sheet(sheet_id=sheet_id, gid=gid, service_account_info=sa)
    except Exception as exc:  # noqa: BLE001
        print("skip live sheet (auth/network):", exc)
        return

    mapping = map_columns(raw)
    assert mapping.get("disbursed_at") in {"Money Received Date", "Tanggal Dana Dilepaskan"}
    assert mapping.get("payment_at") == "Payment Date"
    assert mapping.get("gross") in {"Income", "Total Penghasilan"}
    assert mapping.get("product_name") in {"Variant", "Nama Produk"}

    items = build_line_items(raw)
    assert not items.empty
    assert items["gross_revenue"].sum() > 0
    print("live rows", len(items), "gross", float(items["gross_revenue"].sum()))


if __name__ == "__main__":
    test_parse_url()
    test_parse_url_with_pli()
    test_resolve_sheet_identity_from_secrets()
    test_secrets_get_and_normalize_key()
    test_idr_float()
    test_stock_remaining()
    test_stock_remaining_with_stock_in_simulation()
    test_format_pcs_with_boxes()
    test_demo_metrics()
    test_date_basis_options_always_both()
    test_default_date_range_baseline()
    test_date_basis_filter()
    test_live_sheet_optional()
    print("ok")
