"""RD Collectio — Phase 1 Streamlit sales dashboard."""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from products import (
    COGS_PER_PC,
    PCS_PER_BOX,
    build_line_items,
    demo_line_items,
)
from sheet_loader import DEFAULT_SHEET_URL, fetch_sheet_csv

st.set_page_config(
    page_title="RD Collectio Sales Report",
    page_icon="🍃",
    layout="wide",
    initial_sidebar_state="expanded",
)

ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_CANDIDATES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp", "logo.svg")

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Source+Sans+3:wght@400;500;600;700&display=swap');

:root {
  --rd-ink: #1a2e24;
  --rd-leaf: #2f6b4f;
  --rd-leaf-deep: #1f4a37;
  --rd-mist: #e8f1ec;
  --rd-sand: #f7f4ee;
  --rd-accent: #c45c26;
  --rd-muted: #5c6f65;
}

html, body, [class*="css"] {
  font-family: "Source Sans 3", sans-serif;
  color: var(--rd-ink);
}

.stApp {
  background:
    radial-gradient(1200px 600px at 10% -10%, #d9ebe1 0%, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #f0e6d8 0%, transparent 50%),
    linear-gradient(180deg, #fbfaf7 0%, #f3f6f3 100%);
}

h1, h2, h3, .rd-brand {
  font-family: Fraunces, Georgia, serif !important;
  letter-spacing: -0.02em;
}

.rd-hero {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.25rem;
}

.rd-brand {
  font-size: 1.85rem;
  font-weight: 700;
  color: var(--rd-leaf-deep);
  margin: 0;
  line-height: 1.15;
}

.rd-subtitle {
  color: var(--rd-muted);
  margin: 0.15rem 0 1.25rem 0;
  font-size: 1.02rem;
}

.rd-kpi {
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(47, 107, 79, 0.12);
  border-radius: 14px;
  padding: 1rem 1.1rem 0.9rem;
  box-shadow: 0 8px 24px rgba(26, 46, 36, 0.04);
}

.rd-kpi label {
  display: block;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--rd-muted);
  font-weight: 600;
  margin-bottom: 0.35rem;
}

.rd-kpi strong {
  display: block;
  font-family: Fraunces, Georgia, serif;
  font-size: 1.55rem;
  color: var(--rd-ink);
  line-height: 1.2;
}

.rd-kpi span.hint {
  display: block;
  margin-top: 0.35rem;
  font-size: 0.82rem;
  color: var(--rd-muted);
}

.rd-stock-warn {
  color: #9a3412;
  font-size: 0.82rem;
  margin-top: 0.35rem;
  display: block;
}

.rd-panel {
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(47, 107, 79, 0.1);
  border-radius: 16px;
  padding: 1rem 1.15rem 1.15rem;
}

div[data-testid="stMetricValue"] {
  font-family: Fraunces, Georgia, serif;
}
</style>
"""


def format_idr(value: float) -> str:
    return f"Rp {value:,.0f}".replace(",", ".")


def find_logo() -> Path | None:
    for name in LOGO_CANDIDATES:
        path = ASSETS_DIR / name
        if path.exists():
            return path
    return None


@st.cache_data(show_spinner=False, ttl=300)
def load_live_items(sheet_url: str, refresh_token: int = 0) -> tuple[pd.DataFrame, str]:
    """Load BurnX line items from the sheet.

    ``refresh_token`` is part of the cache key so each Refresh click fetches anew.
    """
    raw = fetch_sheet_csv(sheet_url, cache_bust=str(refresh_token))
    items = build_line_items(raw)
    return items, "live"


def load_items(
    sheet_url: str,
    force_demo: bool,
    refresh_token: int = 0,
) -> tuple[pd.DataFrame, str, str | None]:
    if force_demo:
        return demo_line_items(), "demo", None
    try:
        items, source = load_live_items(sheet_url, refresh_token)
        if items.empty:
            return demo_line_items(), "demo", "Sheet loaded but no BurnX rows were found; showing demo data."
        return items, source, None
    except Exception as exc:  # noqa: BLE001 — surface fetch/parse issues in UI
        return demo_line_items(), "demo", str(exc)


def filter_items(
    items: pd.DataFrame,
    product_filter: list[str],
    start_date,
    end_date,
) -> pd.DataFrame:
    filtered = items.copy()
    if product_filter:
        filtered = filtered[filtered["product_line"].isin(product_filter)]
    if "disbursed_at" in filtered.columns and filtered["disbursed_at"].notna().any():
        dates = pd.to_datetime(filtered["disbursed_at"], errors="coerce")
        mask = pd.Series(True, index=filtered.index)
        if start_date is not None:
            mask &= dates.isna() | (dates.dt.date >= start_date)
        if end_date is not None:
            mask &= dates.isna() | (dates.dt.date <= end_date)
        filtered = filtered[mask]
    return filtered


def pcs_sold_by_product(items: pd.DataFrame) -> dict[str, float]:
    """Sum pcs sold per product line (BurnX Matcha / BurnX Fiber)."""
    totals = {"BurnX Matcha": 0.0, "BurnX Fiber": 0.0}
    if items.empty or "product_line" not in items.columns:
        return totals
    grouped = items.groupby("product_line", as_index=True)["pcs"].sum()
    for line, value in grouped.items():
        if line in totals:
            totals[line] = float(value)
    return totals


def stock_remaining(initial_pcs: float, sold_pcs: float) -> tuple[float, float, bool]:
    """Return (display_remaining, raw_remaining, oversold).

    Display remaining is clamped at 0; oversold is True when sold > initial.
    """
    initial = max(0.0, float(initial_pcs or 0))
    sold = max(0.0, float(sold_pcs or 0))
    raw = initial - sold
    return max(0.0, raw), raw, raw < 0


def sales_recap_table(items: pd.DataFrame) -> pd.DataFrame:
    if items.empty:
        return pd.DataFrame(columns=["Product", "Variant", "Boxes", "Pcs", "Gross", "COGS", "Net"])
    grouped = (
        items.groupby(["product_line", "variant"], as_index=False)
        .agg(
            boxes=("boxes", "sum"),
            pcs=("pcs", "sum"),
            gross_revenue=("gross_revenue", "sum"),
            cogs=("cogs", "sum"),
            net_revenue=("net_revenue", "sum"),
        )
        .sort_values(["product_line", "variant"])
    )
    grouped = grouped.rename(
        columns={
            "product_line": "Product",
            "variant": "Variant",
            "boxes": "Boxes",
            "pcs": "Pcs",
            "gross_revenue": "Gross",
            "cogs": "COGS",
            "net_revenue": "Net",
        }
    )
    return grouped


def main() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    logo = find_logo()
    hero_cols = st.columns([1, 6])
    with hero_cols[0]:
        if logo:
            st.image(str(logo), width=88)
        else:
            st.markdown(
                "<div style='width:72px;height:72px;border-radius:18px;"
                "background:linear-gradient(145deg,#2f6b4f,#1f4a37);"
                "display:flex;align-items:center;justify-content:center;"
                "color:#f7f4ee;font-family:Fraunces,serif;font-size:1.4rem;"
                "font-weight:700;'>RD</div>",
                unsafe_allow_html=True,
            )
    with hero_cols[1]:
        st.markdown('<p class="rd-brand">RD Collectio</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="rd-subtitle">Sales, Performance, and Stock Management Report '
            "· Phase 1 — Shopee sales recap &amp; gross/net revenue</p>",
            unsafe_allow_html=True,
        )

    if "refresh_token" not in st.session_state:
        st.session_state.refresh_token = 0

    with st.sidebar:
        st.header("Data source")
        sheet_url = st.text_input(
            "Sales Report Google Sheets link",
            value=DEFAULT_SHEET_URL,
            help="Paste the full edit URL. The app reads sheet id + gid and loads the CSV export.",
        )
        refresh_clicked = st.button(
            "Refresh",
            type="primary",
            use_container_width=True,
            help="Re-fetch the latest rows from the current sheet link (bypasses cached data).",
        )
        if refresh_clicked:
            st.session_state.refresh_token = int(st.session_state.refresh_token) + 1
            load_live_items.clear()
            st.rerun()

        force_demo = st.toggle("Use demo data", value=False)
        st.caption(
            "Date filter uses **Money Received Date** / **Tanggal Dana Dilepaskan** "
            "(when funds were disbursed to the seller)."
        )
        st.divider()
        st.markdown("**Initial stock (pcs)**")
        st.caption("Remaining = initial − pcs sold in the selected disbursement period.")
        if "initial_stock_matcha" not in st.session_state:
            st.session_state.initial_stock_matcha = 0
        if "initial_stock_fiber" not in st.session_state:
            st.session_state.initial_stock_fiber = 0
        st.number_input(
            "BurnX Matcha (pcs)",
            min_value=0,
            step=1,
            key="initial_stock_matcha",
            help="Starting Matcha inventory in pieces before the selected period.",
        )
        st.number_input(
            "BurnX Fiber (pcs)",
            min_value=0,
            step=1,
            key="initial_stock_fiber",
            help="Starting Fiber inventory in pieces before the selected period.",
        )
        st.divider()
        st.markdown("**COGS reference**")
        st.caption(
            f"Matcha {format_idr(COGS_PER_PC['BurnX Matcha'])}/pc · "
            f"{PCS_PER_BOX['BurnX Matcha']} pcs/box"
        )
        st.caption(
            f"Fiber {format_idr(COGS_PER_PC['BurnX Fiber'])}/pc · "
            f"{PCS_PER_BOX['BurnX Fiber']} pcs/box"
        )
        st.caption("Mixed Matcha → 10 Lemon + 10 Mango. Mixed Fiber → 6/6/6.")

    with st.spinner("Loading sales sheet…"):
        items, source, error = load_items(
            sheet_url,
            force_demo,
            refresh_token=int(st.session_state.refresh_token),
        )

    if error and source == "demo":
        st.warning(f"Could not use the live sheet ({error}). Showing demo data instead.")
    elif source == "live":
        st.success(f"Loaded {len(items)} BurnX line item(s) from the sheet.", icon="✅")
    else:
        st.info("Demo dataset loaded — useful for layout checks and Mixed SKU expansion.")

    if items.empty:
        st.error("No BurnX rows to display.")
        st.stop()

    products = sorted(items["product_line"].dropna().unique().tolist())
    date_series = pd.to_datetime(items["disbursed_at"], errors="coerce").dropna()
    min_date = date_series.min().date() if not date_series.empty else None
    max_date = date_series.max().date() if not date_series.empty else None

    filter_cols = st.columns([2, 1, 1])
    with filter_cols[0]:
        product_filter = st.multiselect("Product lines", options=products, default=products)
    with filter_cols[1]:
        start_date = st.date_input(
            "From (disbursed)",
            value=min_date,
            min_value=min_date,
            max_value=max_date,
            disabled=min_date is None,
        )
    with filter_cols[2]:
        end_date = st.date_input(
            "To (disbursed)",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
            disabled=max_date is None,
        )

    filtered = filter_items(items, product_filter, start_date, end_date)
    # Stock uses the disbursement period only (all BurnX lines), not the product multiselect.
    period_items = filter_items(items, ["BurnX Matcha", "BurnX Fiber"], start_date, end_date)
    if filtered.empty:
        st.warning("No rows match the current filters. Widen the date range or product selection.")
        st.stop()

    gross = float(filtered["gross_revenue"].sum())
    cogs = float(filtered["cogs"].sum())
    net = float(filtered["net_revenue"].sum())
    boxes = float(filtered["boxes"].sum())
    pcs = float(filtered["pcs"].sum())
    orders = filtered["order_id"].nunique()

    k1, k2, k3, k4 = st.columns(4)
    for col, label, value, hint in (
        (k1, "Gross revenue", format_idr(gross), "Sum of Income / Total Penghasilan (BurnX)"),
        (k2, "Net revenue", format_idr(net), "Gross − COGS"),
        (k3, "COGS", format_idr(cogs), "Pcs × per-pc COGS by product line"),
        (k4, "Units sold", f"{boxes:,.1f} boxes · {pcs:,.0f} pcs", f"{orders} order(s)"),
    ):
        with col:
            st.markdown(
                f'<div class="rd-kpi"><label>{label}</label><strong>{value}</strong>'
                f'<span class="hint">{hint}</span></div>',
                unsafe_allow_html=True,
            )

    sold_by_product = pcs_sold_by_product(period_items)
    matcha_initial = float(st.session_state.initial_stock_matcha or 0)
    fiber_initial = float(st.session_state.initial_stock_fiber or 0)
    matcha_sold = sold_by_product["BurnX Matcha"]
    fiber_sold = sold_by_product["BurnX Fiber"]
    matcha_remain, matcha_raw, matcha_over = stock_remaining(matcha_initial, matcha_sold)
    fiber_remain, fiber_raw, fiber_over = stock_remaining(fiber_initial, fiber_sold)

    st.markdown("### Stock remaining")
    period_label = "selected period"
    if start_date and end_date:
        period_label = f"{start_date.isoformat()} → {end_date.isoformat()}"
    st.caption(
        f"Initial stock (sidebar) minus pcs sold in **{period_label}** "
        "(Money Received / disbursement dates). Values clamped at 0 if oversold."
    )
    s1, s2 = st.columns(2)
    for col, title, initial, sold, remain, raw, over in (
        (
            s1,
            "BurnX Matcha",
            matcha_initial,
            matcha_sold,
            matcha_remain,
            matcha_raw,
            matcha_over,
        ),
        (
            s2,
            "BurnX Fiber",
            fiber_initial,
            fiber_sold,
            fiber_remain,
            fiber_raw,
            fiber_over,
        ),
    ):
        warn_html = ""
        if over:
            warn_html = (
                f'<span class="rd-stock-warn">Sold exceeds initial by '
                f"{abs(raw):,.0f} pcs — showing 0 remaining.</span>"
            )
        with col:
            st.markdown(
                f'<div class="rd-kpi"><label>{title}</label>'
                f"<strong>{remain:,.0f} pcs remaining</strong>"
                f'<span class="hint">Initial {initial:,.0f} · Sold in period {sold:,.0f} pcs</span>'
                f"{warn_html}</div>",
                unsafe_allow_html=True,
            )
    if matcha_over or fiber_over:
        st.warning(
            "One or more products sold more pcs than the initial stock you entered "
            "for this period. Remaining is shown as 0 — raise initial stock or narrow the dates."
        )

    st.markdown("### Sales recap")
    st.caption(
        "Units after Mixed SKU expansion. Variants missing from the sheet appear as Unspecified."
    )

    recap = sales_recap_table(filtered)
    display = recap.copy()
    for money_col in ("Gross", "COGS", "Net"):
        display[money_col] = display[money_col].map(format_idr)
    display["Boxes"] = display["Boxes"].map(lambda x: f"{x:,.2f}")
    display["Pcs"] = display["Pcs"].map(lambda x: f"{x:,.0f}")
    st.dataframe(display, use_container_width=True, hide_index=True)

    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.markdown("#### Pcs by variant")
        pcs_chart = (
            alt.Chart(recap)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#2f6b4f")
            .encode(
                x=alt.X("Pcs:Q", title="Pieces"),
                y=alt.Y("Variant:N", sort="-x", title=None),
                color=alt.Color(
                    "Product:N",
                    scale=alt.Scale(
                        domain=["BurnX Matcha", "BurnX Fiber"],
                        range=["#2f6b4f", "#c45c26"],
                    ),
                ),
                tooltip=["Product", "Variant", "Pcs", "Boxes"],
            )
            .properties(height=280)
        )
        st.altair_chart(pcs_chart, use_container_width=True)

    with chart_cols[1]:
        st.markdown("#### Gross vs net by product")
        long = recap.melt(
            id_vars=["Product"],
            value_vars=["Gross", "Net"],
            var_name="Metric",
            value_name="Amount",
        )
        long = long.groupby(["Product", "Metric"], as_index=False)["Amount"].sum()
        money_chart = (
            alt.Chart(long)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("Product:N", title=None),
                y=alt.Y("Amount:Q", title="IDR", axis=alt.Axis(format="~s")),
                color=alt.Color(
                    "Metric:N",
                    scale=alt.Scale(domain=["Gross", "Net"], range=["#1f4a37", "#7aa892"]),
                ),
                xOffset="Metric:N",
                tooltip=["Product", "Metric", alt.Tooltip("Amount:Q", format=",.0f")],
            )
            .properties(height=280)
        )
        st.altair_chart(money_chart, use_container_width=True)

    with st.expander("Line items (parsed)", expanded=False):
        detail = filtered.copy()
        detail["gross_revenue"] = detail["gross_revenue"].map(format_idr)
        detail["cogs"] = detail["cogs"].map(format_idr)
        detail["net_revenue"] = detail["net_revenue"].map(format_idr)
        st.dataframe(detail, use_container_width=True, hide_index=True)

    st.caption(
        "Non-BurnX products are excluded. Logo placeholder: drop a file at `assets/logo.png`."
    )


if __name__ == "__main__":
    main()
