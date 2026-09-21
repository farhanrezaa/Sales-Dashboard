Sales Dashboard

Streamlit dashboard for **RD Collectio** Shopee sales: BurnX sales recap plus gross / net revenue from a pasteable Google Sheets link.

App title: **RD Collectio Sales, Performance, and Stock Management Report** (stock UI comes later).

## Quick start

```bash
python -m pip install -r requirements.txt
streamlit run app.py --server.port 45123
```


## Google Sheets

1. Share the spreadsheet as **Anyone with the link → Viewer**.
2. Paste the full edit URL into the sidebar (sheet id + `gid` are parsed automatically, including `pli=1` links).
3. Click **Refresh** anytime to clear Streamlit cache and re-fetch CSV from the current link.

## Metrics

| Metric | Definition |
| --- | --- |
| Gross revenue | Sum of **Income** (ledger tab) or **Total Penghasilan** (Shopee export) on BurnX rows |
| COGS | Pieces × per-pc COGS (Matcha Rp 16.325 · Fiber Rp 11.500) |
| Net revenue | Gross − COGS |
| Sales recap | Boxes / pcs by product + variant after Mixed expansion |

### Product rules

- **BurnX Matcha** — Mango, Lemon · 20 pcs / box
- **BurnX Fiber** — Strawberry, Raspberry, Blackcurrant · 18 pcs / box
- **BurnX Matcha - Mixed** → 10 Lemon + 10 Mango
- **BurnX Fiber - Mixed** → 6 + 6 + 6 across Fiber variants
- Non-BurnX SKUs (e.g. Shopee Ads) are ignored

## Branding / logo

Place the brand mark at `assets/logo.png`. Until then the app shows an **RD** monogram. See `assets/README.md`.
