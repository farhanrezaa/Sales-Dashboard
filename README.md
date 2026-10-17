# RD Collectio Sales Dashboard

Streamlit Phase 1 dashboard for **RD Collectio** Shopee sales: BurnX sales recap plus gross / net revenue from a private Google Sheet (service account) or optional public CSV fallback.

App title: **RD Collectio Sales, Performance, and Stock Management Report**.

## Quick start

```bash
python -m pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml with your SHEET_ID / SHEET_GID and service-account JSON fields
streamlit run app.py --server.port 45123
```

Open [http://127.0.0.1:45123](http://127.0.0.1:45123).

Without secrets (or if fetch fails), the app falls back to built-in demo data so the UI still runs. Click **Refresh** anytime to clear cache and re-fetch.

## Private Google Sheet (recommended)

1. In Google Cloud: create a service account, download its JSON key.
2. Enable **Google Sheets API** and **Google Drive API** on that GCP project (Drive is required for `open_by_key` / file access).
3. Share the spreadsheet with the service account `client_email` as **Viewer**.
4. Put credentials + sheet identity in Streamlit secrets (local `.streamlit/secrets.toml` or Community Cloud **Secrets**). Never commit the real key.

### Streamlit secrets shape

Use this TOML (same shape on Community Cloud). Replace placeholders — do not paste real private keys into git or chat:

```toml
SHEET_ID = "your-spreadsheet-id"
SHEET_GID = "792137116"

[gcp_service_account]
type = "service_account"
project_id = "your-gcp-project"
private_key_id = "xxxxxxxx"
private_key = """-----BEGIN PRIVATE KEY-----
xxxxxxxx
-----END PRIVATE KEY-----
"""
client_email = "your-sa@your-gcp-project.iam.gserviceaccount.com"
client_id = "1234567890"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "https://www.googleapis.com/robot/v1/metadata/x509/your-sa%40your-gcp-project.iam.gserviceaccount.com"
universe_domain = "googleapis.com"
```

Notes:

- `st.secrets["gcp_service_account"]` must match the JSON key fields.
- `SHEET_ID` is required for the default private path. `SHEET_GID` selects the tab (optional; defaults to the first sheet).
- Optional: `SHEET_URL` instead of / in addition to id+gid (id/gid are parsed from the URL).
- Local example file: `.streamlit/secrets.toml.example`. Real `.streamlit/secrets.toml` is gitignored.
- Sidebar URL field is an **optional override** for local testing; when blank, secrets win.

### Community Cloud Secrets checklist

1. Deploy from GitHub with main file `app.py`.
2. App settings → **Secrets** → paste the TOML above (with real values).
3. Confirm the sheet is shared with `client_email` as Viewer.
4. Confirm Sheets API + Drive API are enabled.
5. Redeploy / reboot the app, then click **Refresh** in the sidebar.

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
4. Add Secrets (see above). Do **not** rely on a public “Anyone with the link” sheet.

## Sheet-column assumptions

Supports two layouts:

### RD Collectio ledger (default tab via `SHEET_GID`)
- Header row with **Payment Date**, **Money Received Date**, **Variant**, **Qty Sold**, **Income**.
- Gross = **Income** (IDR-formatted).
- Date basis filter (draft → **Apply**): **Disbursed Date** and **Payment Date** are always listed. Defaults: **From** = **2026-09-23** (initial stock as-of), **To** = today (applied on first load). All KPIs, sales recap, and remaining stock use the applied basis + range; rows missing the selected date are excluded.
- Remaining stock: defaults **as of 23 Sep 2026** (Matcha Lemon 220 / Mango 200; Fiber Strawberry 270 / Raspberry 240 / Blackcurrant 185). Add dated **incoming** stock events in the sidebar. Formula: `remaining = initial + incoming([From, To]) − sold([From, To])`. Shows pcs with box estimate (Fiber 18 / Matcha 20), e.g. `27 pcs (1.5 box)`.
- **Qty Sold** is piece counts (`Capital per 1 pcs` present). Multi-line Variant cells are split and qty/income shared.
- Mixed SKUs and named variants parsed from Variant text; Ads rows skipped.

### Shopee income export (legacy)
- Multi-row headers; **Nama Produk** / **Total Penghasilan** / **Tanggal Dana Dilepaskan**.
- Revenue uses **Sku** rows (not **Order** rows).
- Quantity: `Jumlah` / `Qty` when present; otherwise **1 box per Sku line**.
