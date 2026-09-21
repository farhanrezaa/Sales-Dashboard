"""Lightweight checks for sheet parsing and BurnX metrics."""

from __future__ import annotations

from products import build_line_items, demo_line_items, map_columns, _to_float
from sheet_loader import DEFAULT_SHEET_URL, fetch_sheet_csv, parse_sheet_url

NEW_SHEET_ID = "1uInQ3r5p0ye8t5PqXEb5J7Jltwtxn1sZ8KB1vf8sr9o"
NEW_GID = "792137116"


def test_parse_url() -> None:
    sheet_id, gid = parse_sheet_url(DEFAULT_SHEET_URL)
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


def test_idr_float() -> None:
    assert _to_float("IDR30,000") == 30_000
    assert _to_float("-IDR500,000") == -500_000


def test_stock_remaining() -> None:
    def stock_remaining(initial_pcs: float, sold_pcs: float):
        initial = max(0.0, float(initial_pcs or 0))
        sold = max(0.0, float(sold_pcs or 0))
        raw = initial - sold
        return max(0.0, raw), raw, raw < 0

    remain, raw, over = stock_remaining(100, 40)
    assert remain == 60 and raw == 60 and not over
    remain, raw, over = stock_remaining(10, 25)
    assert remain == 0 and raw == -15 and over


def test_demo_metrics() -> None:
    demo = demo_line_items()
    assert not demo.empty
    assert set(demo["product_line"]) <= {"BurnX Matcha", "BurnX Fiber"}
    assert (demo["net_revenue"] == demo["gross_revenue"] - demo["cogs"]).all()


def test_live_sheet_optional() -> None:
    """Live fetch for the default ledger tab."""
    raw = fetch_sheet_csv(DEFAULT_SHEET_URL, cache_bust="test")
    mapping = map_columns(raw)
    assert mapping.get("disbursed_at") in {"Money Received Date", "Tanggal Dana Dilepaskan"}
    assert mapping.get("gross") in {"Income", "Total Penghasilan"}
    assert mapping.get("product_name") in {"Variant", "Nama Produk"}
    assert "Qty Sold" in raw.columns or any("qty" in c.lower() for c in raw.columns)

    items = build_line_items(raw)
    assert not items.empty
    assert items["gross_revenue"].sum() > 0
    assert items["product_line"].isin(["BurnX Matcha", "BurnX Fiber"]).all()
    assert items["disbursed_at"].notna().any()
    print(
        "live rows",
        len(items),
        "gross",
        float(items["gross_revenue"].sum()),
        "net",
        float(items["net_revenue"].sum()),
        "pcs",
        float(items["pcs"].sum()),
        "columns",
        list(raw.columns),
    )


if __name__ == "__main__":
    test_parse_url()
    test_parse_url_with_pli()
    test_idr_float()
    test_stock_remaining()
    test_demo_metrics()
    test_live_sheet_optional()
    print("ok")
