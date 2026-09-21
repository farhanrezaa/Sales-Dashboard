"""BurnX product parsing, COGS, and mixed-SKU expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

COGS_PER_PC = {
    "BurnX Fiber": 11_500,
    "BurnX Matcha": 16_325,
}

PCS_PER_BOX = {
    "BurnX Fiber": 18,
    "BurnX Matcha": 20,
}

MATCHA_VARIANTS = ("Mango", "Lemon")
FIBER_VARIANTS = ("Strawberry", "Raspberry", "Blackcurrant")

MIXED_SPLITS = {
    "BurnX Matcha": {"Lemon": 10, "Mango": 10},
    "BurnX Fiber": {"Strawberry": 6, "Raspberry": 6, "Blackcurrant": 6},
}


@dataclass(frozen=True)
class ParsedProduct:
    product_line: Optional[str]
    variant: Optional[str]
    is_mixed: bool
    is_burnx: bool
    boxes: float
    pcs: float


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def detect_product_line(name: str) -> Optional[str]:
    lower = name.lower()
    if "burnx" not in lower and "burn x" not in lower:
        return None
    if "matcha" in lower:
        return "BurnX Matcha"
    # Titles like "Spencer's BurnX - Minuman Tinggi Serat..." are Fiber
    if "fiber" in lower or "serat" in lower:
        return "BurnX Fiber"
    return "BurnX Fiber"


def detect_variant(name: str, product_line: Optional[str]) -> tuple[Optional[str], bool]:
    lower = name.lower()
    if re.search(r"\bmixed\b|\bcampur\b|\bmix\b", lower):
        return None, True

    candidates = {
        "BurnX Matcha": MATCHA_VARIANTS,
        "BurnX Fiber": FIBER_VARIANTS,
    }.get(product_line or "", MATCHA_VARIANTS + FIBER_VARIANTS)

    for variant in candidates:
        if variant.lower() in lower:
            return variant, False
    return None, False


def _to_float(value: object) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text in {"-", "nan", "None", "#DIV/0!", "#N/A"}:
        return None
    # Ledger cells look like "IDR30,000" / "-IDR500,000" (no word break before digits)
    text = re.sub(r"(?i)idr", "", text)
    text = text.replace(",", "").replace(" ", "").replace("\u00a0", "")
    try:
        return float(text)
    except ValueError:
        return None


def quantity_as_pcs(df: pd.DataFrame, column_map: dict[str, str]) -> bool:
    """True when Qty Sold is piece counts (RD Collectio ledger with Capital per 1 pcs)."""
    qty_col = _clean(column_map.get("quantity", "")).lower()
    if qty_col in {"qty sold", "pcs", "pieces", "jumlah pcs"}:
        return True
    headers = {_clean(c).lower() for c in df.columns}
    return "capital per 1 pcs" in headers or "money received date" in headers


def infer_pcs_and_boxes(
    row: pd.Series,
    product_line: Optional[str],
    column_map: dict[str, str],
    qty_is_pcs: bool,
) -> tuple[float, float]:
    """Return (pcs, boxes). Default: 1 box when qty is missing."""
    if not product_line:
        return 0.0, 0.0

    qty_col = column_map.get("quantity")
    qty = _to_float(row[qty_col]) if qty_col and qty_col in row.index else None

    if qty is None or qty <= 0:
        boxes = 1.0
        return boxes * PCS_PER_BOX[product_line], boxes

    if qty_is_pcs:
        pcs = qty
        return pcs, pcs / PCS_PER_BOX[product_line]

    # Shopee-style: qty often boxes; convert when it looks like full piece multiples.
    if qty >= PCS_PER_BOX[product_line] and qty % PCS_PER_BOX[product_line] == 0:
        boxes = qty / PCS_PER_BOX[product_line]
        return qty, boxes
    boxes = qty
    return boxes * PCS_PER_BOX[product_line], boxes


def parse_product_row(
    row: pd.Series,
    column_map: dict[str, str],
    qty_is_pcs: bool = False,
) -> ParsedProduct:
    name_col = column_map.get("product_name")
    variant_col = column_map.get("variant")
    name = _clean(row[name_col]) if name_col and name_col in row.index else ""
    variant_text = _clean(row[variant_col]) if variant_col and variant_col in row.index else ""
    # Prefer the richer of the two (ledger puts full SKU in Variant only).
    combined = name if len(name) >= len(variant_text) else variant_text
    if name and variant_text and name != variant_text:
        combined = f"{name} {variant_text}".strip()

    product_line = detect_product_line(combined)
    is_burnx = product_line is not None
    variant, is_mixed = detect_variant(combined, product_line)
    pcs, boxes = (
        infer_pcs_and_boxes(row, product_line, column_map, qty_is_pcs)
        if is_burnx
        else (0.0, 0.0)
    )

    return ParsedProduct(
        product_line=product_line,
        variant=variant,
        is_mixed=is_mixed,
        is_burnx=is_burnx,
        boxes=boxes,
        pcs=pcs,
    )


def split_sku_lines(text: object) -> list[str]:
    """Split multi-SKU cells ('BurnX Matcha - Mango\\nBurnX Matcha - Lemon')."""
    raw = str(text or "")
    parts = re.split(r"[\n\r]+", raw)
    return [_clean(p) for p in parts if _clean(p)]


def map_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map normalized header names to actual dataframe columns."""
    normalized = {_clean(c).lower(): c for c in df.columns}
    mapping: dict[str, str] = {}

    # Exact-match first; avoid loose substring hits on Shopee refund/fee columns.
    aliases = {
        "product_name": ["nama produk", "product name", "nama barang"],
        "variant": ["nama variasi", "variasi", "variation", "variant", "nama varian"],
        "row_type": ["lihat berdasarkan", "view by", "tipe baris"],
        "order_id": ["no. pesanan", "no pesanan", "order id", "nomor pesanan"],
        "disbursed_at": [
            "tanggal dana dilepaskan",
            "waktu dana dilepaskan",
            "tanggal pencairan",
            "disbursement date",
            "money received date",
        ],
        "ordered_at": ["waktu pesanan dibuat", "tanggal pesanan", "order time"],
        # Ledger "Income" is gross (replaces Total Penghasilan on this tab).
        "gross": ["total penghasilan", "income", "penghasilan", "gross revenue"],
        "product_price": ["harga produk", "product price"],
        "quantity": ["qty sold", "jumlah produk", "kuantitas", "qty", "quantity", "jumlah"],
    }
    # Keys that must not use substring matching (too many false positives).
    exact_only = {"quantity", "gross"}

    for key, names in aliases.items():
        for candidate in names:
            if candidate in normalized:
                mapping[key] = normalized[candidate]
                break
        if key in mapping or key in exact_only:
            continue
        for candidate in names:
            for ncol, original in normalized.items():
                if candidate != ncol and candidate in ncol:
                    mapping[key] = original
                    break
            if key in mapping:
                break

    # Ledger tab: only "Variant" holds the SKU label.
    if "product_name" not in mapping and "variant" in mapping:
        mapping["product_name"] = mapping["variant"]
    return mapping


def expand_mixed_to_variants(product_line: str, boxes: float) -> dict[str, float]:
    split = MIXED_SPLITS[product_line]
    # Mixed splits are defined per box; scale by boxes → pcs per variant
    return {variant: count * boxes for variant, count in split.items()}


def _append_line_records(
    records: list[dict],
    *,
    order_id: str,
    parsed: ParsedProduct,
    gross: float,
    disbursed,
    ordered,
    product_name: str,
) -> None:
    if not parsed.is_burnx or not parsed.product_line or parsed.pcs <= 0:
        return

    if parsed.is_mixed:
        variant_pcs = expand_mixed_to_variants(parsed.product_line, parsed.boxes)
    elif parsed.variant:
        variant_pcs = {parsed.variant: parsed.pcs}
    else:
        variant_pcs = {"Unspecified": parsed.pcs}

    cogs_rate = COGS_PER_PC[parsed.product_line]
    for variant, pcs in variant_pcs.items():
        boxes_equiv = pcs / PCS_PER_BOX[parsed.product_line]
        share = pcs / parsed.pcs if parsed.pcs else 0.0
        line_gross = gross * share
        line_cogs = pcs * cogs_rate
        records.append(
            {
                "order_id": order_id,
                "product_line": parsed.product_line,
                "variant": variant,
                "is_mixed_source": parsed.is_mixed,
                "boxes": boxes_equiv,
                "pcs": pcs,
                "gross_revenue": line_gross,
                "cogs": line_cogs,
                "net_revenue": line_gross - line_cogs,
                "disbursed_at": disbursed,
                "ordered_at": ordered,
                "product_name": product_name,
            }
        )


def build_line_items(df: pd.DataFrame) -> pd.DataFrame:
    """Return BurnX SKU-level line items with COGS and expanded variant pcs."""
    if df.empty:
        return pd.DataFrame()

    column_map = map_columns(df)
    if "product_name" not in column_map:
        raise ValueError(
            "Could not find a product name column (Nama Produk / Variant) in the sheet."
        )

    qty_is_pcs = quantity_as_pcs(df, column_map)
    records: list[dict] = []

    for _, row in df.iterrows():
        row_type = _clean(row[column_map["row_type"]]).lower() if "row_type" in column_map else ""
        # Prefer SKU rows when the Shopee export includes Order + Sku pairs
        if row_type and row_type not in {"sku", "product", "item"}:
            continue

        name_col = column_map["product_name"]
        variant_col = column_map.get("variant", name_col)
        label_source = row[variant_col] if variant_col in row.index else row[name_col]
        sku_lines = split_sku_lines(label_source)
        if not sku_lines:
            continue

        gross = _to_float(row[column_map["gross"]]) if "gross" in column_map else 0.0
        gross = gross or 0.0

        disbursed = None
        if "disbursed_at" in column_map:
            disbursed = pd.to_datetime(row[column_map["disbursed_at"]], errors="coerce", dayfirst=True)
        ordered = None
        if "ordered_at" in column_map:
            ordered = pd.to_datetime(row[column_map["ordered_at"]], errors="coerce")

        order_id = _clean(row[column_map["order_id"]]) if "order_id" in column_map else ""

        # Total pcs/boxes on the row (shared across newline-split SKUs).
        qty_col = column_map.get("quantity")
        raw_qty = _to_float(row[qty_col]) if qty_col and qty_col in row.index else None

        # Filter to BurnX lines only for allocation
        burnx_lines = [line for line in sku_lines if detect_product_line(line)]
        if not burnx_lines:
            continue

        n = len(burnx_lines)
        for line in burnx_lines:
            product_line = detect_product_line(line)
            assert product_line is not None
            variant, is_mixed = detect_variant(line, product_line)

            if raw_qty is not None and raw_qty > 0:
                if qty_is_pcs:
                    pcs = raw_qty / n
                    boxes = pcs / PCS_PER_BOX[product_line]
                else:
                    boxes = raw_qty / n
                    pcs = boxes * PCS_PER_BOX[product_line]
            else:
                boxes = 1.0 / n
                pcs = boxes * PCS_PER_BOX[product_line]

            parsed = ParsedProduct(
                product_line=product_line,
                variant=variant,
                is_mixed=is_mixed,
                is_burnx=True,
                boxes=boxes,
                pcs=pcs,
            )
            _append_line_records(
                records,
                order_id=order_id,
                parsed=parsed,
                gross=gross / n,
                disbursed=disbursed,
                ordered=ordered,
                product_name=line,
            )

    return pd.DataFrame.from_records(records)


def demo_line_items() -> pd.DataFrame:
    """Synthetic BurnX rows used when the live sheet cannot be fetched."""
    rows = [
        {
            "order_id": "DEMO-001",
            "product_line": "BurnX Matcha",
            "variant": "Mango",
            "is_mixed_source": False,
            "boxes": 2,
            "pcs": 40,
            "gross_revenue": 850_000,
            "cogs": 40 * 16_325,
            "disbursed_at": pd.Timestamp("2026-08-10"),
            "ordered_at": pd.Timestamp("2026-08-08"),
            "product_name": "BurnX Matcha - Mango",
        },
        {
            "order_id": "DEMO-002",
            "product_line": "BurnX Matcha",
            "variant": "Lemon",
            "is_mixed_source": False,
            "boxes": 1,
            "pcs": 20,
            "gross_revenue": 425_000,
            "cogs": 20 * 16_325,
            "disbursed_at": pd.Timestamp("2026-08-12"),
            "ordered_at": pd.Timestamp("2026-08-11"),
            "product_name": "BurnX Matcha - Lemon",
        },
        {
            "order_id": "DEMO-003",
            "product_line": "BurnX Matcha",
            "variant": "Mango",
            "is_mixed_source": True,
            "boxes": 0.5,
            "pcs": 10,
            "gross_revenue": 210_000,
            "cogs": 10 * 16_325,
            "disbursed_at": pd.Timestamp("2026-08-15"),
            "ordered_at": pd.Timestamp("2026-08-14"),
            "product_name": "BurnX Matcha - Mixed",
        },
        {
            "order_id": "DEMO-003",
            "product_line": "BurnX Matcha",
            "variant": "Lemon",
            "is_mixed_source": True,
            "boxes": 0.5,
            "pcs": 10,
            "gross_revenue": 210_000,
            "cogs": 10 * 16_325,
            "disbursed_at": pd.Timestamp("2026-08-15"),
            "ordered_at": pd.Timestamp("2026-08-14"),
            "product_name": "BurnX Matcha - Mixed",
        },
        {
            "order_id": "DEMO-004",
            "product_line": "BurnX Fiber",
            "variant": "Strawberry",
            "is_mixed_source": False,
            "boxes": 3,
            "pcs": 54,
            "gross_revenue": 720_000,
            "cogs": 54 * 11_500,
            "disbursed_at": pd.Timestamp("2026-08-18"),
            "ordered_at": pd.Timestamp("2026-08-17"),
            "product_name": "BurnX Fiber - Strawberry",
        },
        {
            "order_id": "DEMO-005",
            "product_line": "BurnX Fiber",
            "variant": "Raspberry",
            "is_mixed_source": True,
            "boxes": 1 / 3,
            "pcs": 6,
            "gross_revenue": 80_000,
            "cogs": 6 * 11_500,
            "disbursed_at": pd.Timestamp("2026-08-20"),
            "ordered_at": pd.Timestamp("2026-08-19"),
            "product_name": "BurnX Fiber - Mixed",
        },
        {
            "order_id": "DEMO-005",
            "product_line": "BurnX Fiber",
            "variant": "Strawberry",
            "is_mixed_source": True,
            "boxes": 1 / 3,
            "pcs": 6,
            "gross_revenue": 80_000,
            "cogs": 6 * 11_500,
            "disbursed_at": pd.Timestamp("2026-08-20"),
            "ordered_at": pd.Timestamp("2026-08-19"),
            "product_name": "BurnX Fiber - Mixed",
        },
        {
            "order_id": "DEMO-005",
            "product_line": "BurnX Fiber",
            "variant": "Blackcurrant",
            "is_mixed_source": True,
            "boxes": 1 / 3,
            "pcs": 6,
            "gross_revenue": 80_000,
            "cogs": 6 * 11_500,
            "disbursed_at": pd.Timestamp("2026-08-20"),
            "ordered_at": pd.Timestamp("2026-08-19"),
            "product_name": "BurnX Fiber - Mixed",
        },
    ]
    frame = pd.DataFrame(rows)
    frame["net_revenue"] = frame["gross_revenue"] - frame["cogs"]
    return frame
