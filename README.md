# RD Collectio Sales Dashboard

Streamlit Phase 1 dashboard for **RD Collectio** Shopee sales: BurnX sales recap plus gross / net revenue from a pasteable Google Sheets link.

App title: **RD Collectio Sales, Performance, and Stock Management Report** (stock UI comes later).

## Quick start

```bash
python -m pip install -r requirements.txt
streamlit run app.py --server.port 45123
```

Open [http://127.0.0.1:45123](http://127.0.0.1:45123).

## Google Sheets

1. Share the spreadsheet as **Anyone with the link → Viewer**.
2. Paste the full edit URL into the sidebar (sheet id + `gid` are parsed automatically, including `pli=1` links).
3. Click **Refresh** anytime to clear Streamlit cache and re-fetch CSV from the current link.
4. Default Sales Report tab is prefilled:
   `https://docs.google.com/spreadsheets/d/1uInQ3r5p0ye8t5PqXEb5J7Jltwtxn1sZ8KB1vf8sr9o/edit?pli=1&gid=792137116#gid=792137116`
   (sheet id `1uInQ3r5p0ye8t5PqXEb5J7Jltwtxn1sZ8KB1vf8sr9o`, `gid=792137116`)

If the sheet cannot be fetched (private sheet, network, etc.), the app falls back to built-in demo data so the UI still runs.

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

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.
2. At [share.streamlit.io](https://share.streamlit.io), **New app** → select the repo.
3. Set **Main file path** to `app.py`.
4. Deploy. Keep the Google Sheet public-to-view so Cloud can export CSV without secrets.

## Sheet-column assumptions

Supports two layouts:

### RD Collectio ledger (default tab `gid=792137116`)
- Header row with **Money Received Date**, **Variant**, **Qty Sold**, **Income**.
- Gross = **Income** (IDR-formatted). Date filter = **Money Received Date**.
- **Qty Sold** is piece counts (`Capital per 1 pcs` present). Multi-line Variant cells are split and qty/income shared.
- Mixed SKUs and named variants parsed from Variant text; Ads rows skipped.

### Shopee income export (legacy)
- Multi-row headers; **Nama Produk** / **Total Penghasilan** / **Tanggal Dana Dilepaskan**.
- Revenue uses **Sku** rows (not **Order** rows).
- Quantity: `Jumlah` / `Qty` when present; otherwise **1 box per Sku line**.
