# Distributor sales

The browser tool, rebuilt as a proper system: **MySQL** for storage, **Python**
(FastAPI + SQLAlchemy) for the API, **React** for the screens.

What it does is unchanged — take the zip a distributor sends, pick the files
that belong to this run, and produce the twelve-column sheet — but the result is
now kept. Every conversion is a batch you can reopen, search, re-download and
reconcile months later, instead of a download that exists only in someone's
Downloads folder.

## Running it

    cp .env.example .env        # set SECRET_KEY and APP_PASSWORD
    docker compose up -d --build

The API is on `:8000`. For the screens in development:

    cd frontend && npm install && npm run dev     # :5173, proxies /api to :8000

Two settings are not optional:

* **`APP_PASSWORD`** — the one password that opens the tool. Without it the API
  refuses every sign-in rather than letting anyone in.
* **`SECRET_KEY`** — signs the session tokens. Generate once with
  `openssl rand -hex 32` and never change it; changing it signs everybody out.

## The shape of it

**Distributors are data, not code.** Each one carries its own cut-off day,
invoice numbering, return handling and the pattern naming the files its rule
wants. The three are seeded on first run:

| | Cut-off | Invoice No | Files it picks |
|---|---|---|---|
| Yetichem | 15th | `INV - 1` sequence | `PW` workbooks |
| Pharmachem | 10th | read from the file | chosen by hand |
| Gunjeshwari | 10th | `INV - 1` sequence | chosen by hand |

Edit them on the **Rules** screen. A cut-off corrected there is not undone by
the next restart, and a batch already converted keeps the rules it was made
with.

**Two file layouts are read**, decided from the file rather than its name: the
cross-tab (products down, customers across, quantities and amounts on alternate
rows) and plain row-wise sheets. A sheet named as a return has its quantities
and amounts negated. A stocks file is refused with a reason rather than
half-read.

**Nothing is chosen for you.** No distributor is pre-selected, and in a zip only
the files that distributor's own rule names are ticked. Converting a stocks file
silently would be worse than asking.

**Both sides of the decision are stored.** `batch_file` records every workbook
that was offered *and* whether it was used, and the Notes tab in the download
repeats it. When a total looks wrong, the first question — did we convert the
right files? — is answered inside the workbook.

## The rules, in one place

`app/services/rules.py`. On or before the cut-off: the month steps back one and
Mid Month is `N`. After it: the current month, and `Y`. Year is the current
year, as the rule says — including the one case where the month steps back past
January and the year then reads oddly. The screen warns about that case rather
than silently correcting a stated rule; say the word and it can step back too.

## Tests

    cd backend && pytest -q        # 62 tests (27 conversion + 30 master data + 5 legacy import)

They cover the gate (every route is walked without a token and must refuse),
the month rule across the year and both cut-offs, the parser against the real
workbooks, and the whole journey — inspect, commit, read back, export — with the
totals checked at each step. The suite asserts the numbers this replaced:
**82 rows, 140 omitted, 43,200 quantity, 27,65,117.77**.

## Master data

The **Masters** screen holds the structure sales are reported against, grouped
down the left-hand side:

| Group | Masters |
|---|---|
| Setup | Years, Distributors, Companies, Countries, Currency rates, Company › Countries |
| Geography | Zones › Headquarters › Territories |
| Products | Product groups › Brands › SKUs, Product reporting (P1 / P2 / X), Product reporting › SKUs |
| Customers | Customers (Customer ID, name, classification) |
| People | Designations, Roles, Teams, Team › Product groups, Team › Headquarters, Employees |
| Alignment | Customer alignment, Employee alignment (both at SKU level) |

**Structure is permanent; alignment is per year.** A territory sits under one
HQ and an SKU under one brand, and that does not change year to year. Which team
carries which product group, and which customer and employee cover which SKU in
which territory, is realigned every year — so every alignment row carries a
Year, and last year's alignment stays readable. *Copy from a year* starts a new
year from the old one; change only what moved.

**The rules between masters are enforced, with the fix in the message.** A
customer's SKU can only be assigned to a team that carries its product group
and covers its territory's HQ that year. A SKU reports under one line per year.
A reporting line cannot go round in a circle. A row still in use cannot be
deleted — the message says what uses it, and suggests marking it inactive.

**SKU level without typing every SKU.** *Assign a whole group* adds one row per
active SKU of a product group (or one brand of it), skipping any already there.

**INR and NPR.** India and Nepal are seeded, with the rate at the 1.60 peg from
2000-01-01 — confirm it. A rate is kept one way (INR → NPR) and the other way is
its inverse, so the two can never disagree; a new rate applies from its date.
`GET /api/currency/convert?amount=&frm=NPR&to=INR&on=` converts on any day.

**One definition drives everything.** `app/masters/specs.py` describes each
master — fields, uniqueness, validation, what points at it. The API and the
screens are both drawn from it, so a field added there appears on the screen
with no front-end change.

**Upgrading an existing database** needs nothing by hand: on startup the API
creates the new `md_*` tables and adds the new distributor columns (Code,
Country, contact details). To apply by hand instead: `migrations/001_…sql`
(old databases only), then `schema.sql`, then `schema_masters.sql`.

## Importing the old SQL Server data

**Masters › Tools › Import old data** brings the old Abbott masters across.

1. In SQL Server Management Studio run `SELECT * FROM dbo.<TABLE>` for each table
   below, right-click the results → **Copy with Headers**, paste into Excel and
   save as `<TABLE>.xlsx` (for example `PRODUCT_MASTER.xlsx`). One workbook with
   a sheet per table, each sheet named after its table, works too.
2. Choose all the files, press **Check** (a dry run: nothing is saved), read the
   report, then press **Import**.

| Old table | Becomes |
|---|---|
| PRODUCT_MASTER_GROUP | Product groups |
| PRODUCT_MASTER_BRAND | Brands; REPORTING → a P1/P2/X reporting line per brand; TEAM_ID → Team › Product groups |
| PRODUCT_MASTER | SKUs (SAP id, material code, NRV, dates); PRODUCT_ALIAS_1..100 → SKU aliases |
| ZONE, HQ_MASTER, TERRITORY | Zones › Headquarters › Territories (India by default) |
| CUSTOMER_MASTER | Customers (SAP id, billing name, zone/HQ/territory, dates); CUSTOMER_ALIAS_1..50 → Customer aliases |
| STATE, customer CLASSIFICATION / REMARK, SUB_TERRITORY | Names stored on the customer |
| ROLE_MASTER, DESIGNATION, TEAM | Roles, Designations, Teams (matched by name to teams already typed in) |
| EMPLOYEE_MASTER | Employees, with reporting manager; **passwords are never copied** |

Every imported row keeps its old id in **LegacyId**, so running the import
again updates instead of duplicating, and nothing is ever deleted. A row pointed
at but not sent (a customer's HQ 12 with no HQ file) becomes a placeholder
"HQ #12" until that table is sent. The same import runs from the command line:
`python -m app.services.legacy_import FILE... [--commit] [--year-id N]`.

## What it does not do

* **PDFs.** Gunjeshwari and Pharmachem originally arrived as PDFs. Extracting
  tables from them is unreliable enough that refusing beats handing over
  plausible-looking wrong numbers. Export to Excel first.
* **Linking converted sales rows to the masters.** Batches still store the names
  exactly as the distributor sent them. Mapping those names to Customer IDs and
  SKUs is the natural next step, and the masters are shaped for it.
* **Customer-name mapping.** Gunjeshwari's names were matched against a
  reference list by hand, with two matches flagged as doubtful at the time.
  Names are cleaned here, not mapped.
