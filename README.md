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

## The screens

Dark, in the look of atomsolar.in: a sidebar with Convert, Batches, Rules and
Masters. **Convert** shows the Month, Year and Mid Month every row will carry
before anything is converted. Fonts are Fraunces, Mukta and Michroma from
Google Fonts, with system fallbacks if they cannot load.

## The shape of it

**Distributors are data, not code.** Each one carries its own cut-off day,
invoice numbering, return handling and the pattern naming the files its rule
wants. The three are seeded on first run:

| | Cut-off | Invoice No | Files it picks |
|---|---|---|---|
| Yetichem | 15th | `INV - 1` sequence | the three `PW` workbooks (AHCPW, AILGPW, AILNPW .xls) |
| Pharmachem | 10th (Mid Month: 11th) | read from the file | every Excel file in the zip; sheet 3 sales, sheet 4 returns |
| Gunjeshwari | 10th | `INV - 1` sequence | **ALI BATCHWISE\*.pdf** and **AHL BATCHWISE\*.pdf**, from two zips uploaded together |

Edit them on the **Rules** screen. A cut-off corrected there is not undone by
the next restart, and a batch already converted keeps the rules it was made
with.

**Two file layouts are read**, decided from the file rather than its name: the
cross-tab (products down, customers across, quantities and amounts on alternate
rows) and plain row-wise sheets. Both are read from Excel workbooks and from
PDF reports. A sheet named as a return has its quantities
and amounts negated. A stocks file is refused with a reason rather than
half-read.

**Nothing is chosen for you.** No distributor is pre-selected, and in a zip only
the files that distributor's own rule names are ticked. Converting a stocks file
silently would be worse than asking.

**Both sides of the decision are stored.** `batch_file` records every workbook
that was offered *and* whether it was used, and the Notes tab in the download
repeats it. When a total looks wrong, the first question — did we convert the
right files? — is answered inside the workbook.

## Yetichem's three PW workbooks

Yetichem sends a zip with **AHCPW.xls**, **AILGPW.xls** and **AILNPW.xls**,
cross-tab workbooks in the older Excel format (read with `xlrd`; a file named
.xls that is really an .xlsx is opened as one). Choose Yetichem on **Convert**
and drop the zip: the three PW files are ticked (pattern `PW\.(xlsx|xlsm|xls)$`),
a stocks file is not, and the three become one sheet.

### The rule, as given

| # | Rule | Where it is done |
|---|---|---|
| 1 | Distributor Name is always Yetichem | the distributor chosen on Convert |
| 2 | Invoice No is `INV - 1`, `INV - 2` … one per row, running across all three files | Invoice No = `INV - 1` sequence |
| 3 | Uploaded on the 1st–15th: Month is the previous month, otherwise the current month, written in full | cut-off day 15 |
| 4 | Year is the current year, YYYY | the month rule |
| 5 | Uploaded on the 1st–15th: Mid Month is N, otherwise Y | cut-off day 15 |
| 6–7 | Customer Name and Product Name from the file | cross-tab: customers across, products down |
| 8 | Quantity and Free Quantity from cells like `40 + 0` (40 bought, 0 free). `-40 + 0` (or `- 40 + 0`) is a quantity of -40; quantities below 0 are kept | `parse.QTY` |
| 9 | Rate = Amount / Quantity (0 for a free-only line) | Rate = **Amount ÷ Quantity** on Rules |
| 11 | B.Amount and Amount are the same, read from the file (the row under the quantities) | |
| — | Special characters removed from customer and product names; rows with quantity and free quantity both 0 are left out, as are Total rows and columns | `parse.clean`, cross-tab reader |

## Pharmachem's four workbooks

Pharmachem sends a zip of **four Excel files**. Choose Pharmachem on **Convert**
and drop the zip: every workbook in it is ticked (pattern `\.(xlsx|xlsm|xls)$`)
and the four become one sheet. From each workbook **sheet 3 is read as sales and
sheet 4 as sales returns**; the other sheets are left alone. A sheet named
`Sheet3` / `Sheet 4` is taken first, otherwise the third and fourth in order.

### The rule, as given

| # | Rule | Where it is done |
|---|---|---|
| 1 | Distributor Name is always Pharmachem | the distributor chosen on Convert |
| 2 | Invoice No read from the file (filled down where a bill's later lines leave it blank) | Invoice No = **Read from the file** |
| 3 | Uploaded on the 1st–10th: Month is the previous month, otherwise the current month, in full | Month cut-off day 10 |
| 4 | Year is the current year, YYYY | the month rule |
| 5 | Uploaded on the 1st–**11th**: Mid Month is N, otherwise Y | **Mid Month cut-off day 11**, its own setting on Rules |
| 6–7 | Customer Name and Product Name from the file | `parse.read_register` |
| 8 | Quantity and Free Quantity from the file; positive on sheet 3, negative on sheet 4 | Sales / Sales return sheet = 3 / 4 |
| 9 | Rate from the file (a price, so never negative) | Rate = **Read from the file** |
| 11 | B.Amount and Amount each read from its own column; positive on sheet 3, negative on sheet 4 | `parse.read_register` |
| — | All special characters omitted from customer and product names, except that the `.` is kept in product names | Product names = **Keep the '.'** |

Rules 3 and 5 name different days, and are kept as written: on the 11th, Month
is the current month and Mid Month is still N. Change either on **Rules**.

The register is read from its header row, in the usual words (Invoice / Bill
No, Party / Customer, Item / Product, Qty, Free / Sch, Rate / PTR, B.Amount /
Basic / Gross, Amount / Net Amount). Total lines and lines with quantity and
free both 0 are left out. Sheet 3 rows are positive and sheet 4 rows negative
whatever sign the file printed, as the rule says.

## Gunjeshwari's two zips of PDFs

Gunjeshwari sends **two zip files**, uploaded together. The files to convert are
the ones named **ALI BATCHWISE\*.pdf** and **AHL BATCHWISE\*.pdf** extracted from
them. Choose Gunjeshwari on **Convert** and drop both zips at once: those PDFs are
ticked (pattern `(ali|ahl)\s*batch\s*wise[^/]*\.pdf$`, case-blind, editable on
**Rules**) and combined into one .xlsx sheet. If both zips hold a file with the
same name, both are kept (the second as `name (2).pdf`).

### Choosing the files — under all conditions

For Gunjeshwari **every file extracted from the zips is listed and can be
ticked**, whatever its name, its type, or whether the reader understood it at
first sight. The ALI/AHL BATCHWISE pattern only decides what is ticked to begin with; what
you tick is what is converted, and that choice overrides the file-name rule.

* Every file in the zip is offered (not only PDFs and workbooks), a zip inside
  the zip is opened too, and two files with the same name in different folders
  are both kept (the second as `name (2).pdf`). Only folders and the `__MACOSX`
  / `._` / `.DS_Store` files a Mac adds are left out.
* A ticked file is read under the rules below. If the strict reading finds
  nothing, it is read more loosely: a header in other words (A/c Name, Party,
  Description, Sale Qty, Sch, PTR, Value …); no customer column, with the party
  taken from a heading line (`Party Name : …`) above the items; no amount
  column, with Amount = Quantity × Rate; and for a PDF with no table at all,
  line by line — a line of words names the party, a line ending in figures is a
  sale, a line starting with a batch number carries on the product above.
  CSV/text files are read too.
* A ticked file in which nothing can be found does not stop the batch; it is
  named in the batch notes. If none of the ticked files has rows, the convert is
  refused and the files are named.

Which distributors work this way is `SELECT_ANY` in `app/services/seed.py`
(Gunjeshwari only); Yetichem and Pharmachem are unchanged.

### The rule, as given

Create an Excel sheet (.xlsx) from the ALI BATCHWISE\*.pdf and AHL
BATCHWISE\*.pdf files extracted from the two zips uploaded together, with these
headings: Distributor Name, Invoice No, Month, Year, Mid Month, Customer Name,
Product Name, Quantity, Free Quantity, Rate, B.Amount and Amount.

| # | Rule | Where it is done |
|---|---|---|
| 1 | Distributor Name is always Gunjeshwari | the distributor chosen on Convert |
| 2 | Invoice No is `INV - 1`, `INV - 2`, `INV - 3` … a new number for each row generated | Invoice No = `INV - 1` sequence |
| 3 | Uploaded on the 1st–10th of the month: Month is the previous month (Month − 1), otherwise the current month, written in full (January, February, March …) | cut-off day 10 |
| 4 | Year is the current year, YYYY | the month rule |
| 5 | Uploaded on the 1st–10th of the current month: Mid Month is N, otherwise Y | cut-off day 10 |
| 6 | Customer Name extracted from the file | the PDF table |
| 7 | Product Name extracted from the file; where a product is repeated on a line that starts from the quantity, that line is entered as a new row with all its entries | fill-down in `parse.read_pdf` |
| 8 | Quantity from the file | |
| 9 | Free Quantity from the file | |
| 10 | Rate from the file | Rate = **Read from the file** on Rules |
| 11 | B.Amount and Amount are the same, read from the file | |
| 12 | Product names replaced with the name in the product Excel sheet where they match | **Reference names** on Convert |
| 13 | Customer names checked against the customer Excel sheet and replaced with the name in it where they match | **Reference names** on Convert |
| — | All special characters are omitted when mapping product and customer names | `services/names.py` |

### Reference names

On **Convert**, once Gunjeshwari is chosen, **Reference names** takes two Excel
files: the customer list and the product list. The name column is the one
headed Customer Name / Customer / Party (or Product Name / Product / Item);
without such a header, the first column with text. Each list is kept until a new
one is uploaded, so it is sent once, not with every zip.

A name matches when the two are equal after removing case, spaces and every
special character, so *Shree Medical Hall (P) Ltd.* matches *SHREE MEDICAL HALL
P LTD*. The list's spelling goes into the sheet. Names with no match are kept as
extracted and listed in the batch notes and the **Notes** tab of the download,
so the list can be completed.

### How a PDF is read

* Every table on every page is joined into one list. Ruled tables are read from
  their lines; a report printed without lines from the gaps between words.
* The header row has to name customer (or party), product (or item), quantity
  and amount; Free and Rate are read when present. The header repeated on each
  page is dropped.
* A party or product printed once as a heading is carried down onto the lines
  below it. A line with figures and a rate but no names continues the product
  above (a further batch); one with no rate is a subtotal and is left out, as
  are lines labelled Total.

A database from before this change is brought forward on startup: the pick
pattern is set if empty or still the old Batch default, and the description and Rate-from-file are set only if
Gunjeshwari's note was still a seeded default — anything typed on Rules stays.

## The rules, in one place

`app/services/rules.py`. On or before the cut-off: the month steps back one and
Mid Month is `N`. After it: the current month, and `Y`. A distributor can give
Mid Month its own cut-off (Pharmachem: 10th for the month, 11th for Mid Month). Year is the current
year, as the rule says — including the one case where the month steps back past
January and the year then reads oddly. The screen warns about that case rather
than silently correcting a stated rule; say the word and it can step back too.

## Tests

    cd backend && pytest -q        # conversion, PDF, Yetichem, Gunjeshwari, Pharmachem, master data and master upload

`tests/test_api.py` reads a sample zip (FW__MID-MONTH_SALES.zip) from
/mnt/user-data/uploads; put it there, or those tests error.

They cover the gate (every route is walked without a token and must refuse),
the month rule across the year and both cut-offs, the parser against the real
workbooks, and the whole journey — inspect, commit, read back, export — with the
totals checked at each step. The suite asserts the numbers this replaced:
**82 rows, 140 omitted, 43,200 quantity, 27,65,117.77**.

## Master data

The **Masters** screen holds the structure sales are reported against:

| Group | Masters |
|---|---|
| Setup | Years, Distributors, Companies, Countries, Currency rates, Company › Countries |
| Geography | Zones › Headquarters › Territories |
| Products | Product groups, **Brands** (`PRODUCT_MASTER_BRAND`), **Products** (`PRODUCT_MASTER`), Product reporting (P1 / P2 / X), Product reporting › SKUs |
| Customers | **Customers** (`CUSTOMER_MASTER`) |
| People | Designations, Roles, Teams, Team › Product groups, Team › Headquarters, **Employees** (`EMPLOYEE_MASTER`) |
| Alignment | Customer alignment, Employee alignment (both at product level) |

### The tables of MASTER DATA & TABLES.xlsx

Customers, Brands, Products and Employees are the four tables of MASTER DATA &
TABLES.xlsx, **with its table and column names**: `CUSTOMER_MASTER` (64
columns), `PRODUCT_MASTER` (110), `PRODUCT_MASTER_BRAND` and `EMPLOYEE_MASTER`.
They replace the earlier `md_customer`, `md_sku`, `md_brand` and `md_employee`.

* **Aliases live on the row.** `CUSTOMER_ALIAS_1`–`50` and
  `PRODUCT_ALIAS_1`–`100` are columns, as in the workbook, edited as one list
  (a name per line). The separate *Customer aliases* and *SKU aliases* screens
  are gone. Search finds a row by any of its aliases.
* **IDs are the workbook's.** `CUSTOMER_ID`, `PRODUCT_ID` … are kept as
  uploaded and cannot be changed afterwards; a row added on screen without one
  gets the next number.
* **Master IDs link them to their parents.** `ZONE_ID`, `HQ_ID`,
  `TERRITORY_ID`, `PRODUCT_GROUP_ID`, `TEAM_ID`, `ROLE_ID` and `DESIGNATION_ID`
  hold the parent's **Master ID** — a column on Zones, Headquarters,
  Territories, Product groups, Teams, Roles and Designations, given
  automatically if left blank. An ID whose parent is not uploaded yet is kept
  and shown as "12 (not in Zones)"; 0 means none.
* **`PASSWORD` is never stored.** The upload reads past it.
* `REPORTING_MANAGER_ID` equal to the employee's own ID marks the top of the
  tree, as the workbook does; a real circle is refused.

### Uploading master data

**Masters › Upload master data** takes MASTER DATA & TABLES.xlsx as it is, or
any workbook / CSV per master. Every master can be uploaded, the same way:

* A sheet is read into the master it is named after: the table name
  (`CUSTOMER_MASTER` …), the old system's (`ZONE`, `HQ_MASTER`, `TERRITORY`,
  `PRODUCT_MASTER_GROUP`, `TEAM`, `ROLE_MASTER`, `DESIGNATION`), or the
  screen's title (Years, Countries …).
* Columns are found by header: the workbook's column name, the screen's label,
  or the old name (`ZONE_NAME`, `HQ_ID` …). A reference is a Master ID, code or
  name. Parents are read before children whatever the sheet order.
* **Check** does the whole upload and rolls it back, showing what would be
  added, updated, unchanged and left out — each left-out row with its reason.
  **Import** then saves. Uploading again updates the same rows; nothing is
  deleted; only the columns a sheet carries are changed.
* Every master page also has **Upload Excel** (that master only) and
  **Download Excel**, which writes the same headers back — so a download is
  also the template. **Download every master** gives one workbook of all.

`POST /api/masters/upload` (files, `dry_run`, optional `slug`),
`GET /api/masters/{slug}/export`, `GET /api/masters/export-all`.

**Structure is permanent; alignment is per year.** *Copy from a year* starts a
new year from the old one. A customer's product can only be assigned to a team
that carries its product group and covers its territory's HQ that year.

**INR and NPR.** India and Nepal are seeded, with the rate at the 1.60 peg from
2000-01-01 — confirm it. `GET /api/currency/convert?amount=&frm=NPR&to=INR&on=`.

**One definition drives everything.** `app/masters/specs.py` describes each
master — fields, uniqueness, validation, upload names. The API, the screens and
the upload are all drawn from it.

**Upgrading an existing database** needs nothing by hand: on startup the API
creates the new tables, adds the new columns, gives existing parents a Master
ID and repoints the alignment keys. The old `md_customer` / `md_sku` /
`md_brand` / `md_employee` / alias tables are left in place unused; see
`migrations/003_master_data_tables.sql` to drop them once the masters are
uploaded again.

## What it does not do

* **Scanned PDFs.** A PDF is read from its text (`pdfplumber`), so a scan or
  photo has nothing to read and is refused with a reason rather than guessed at.
* **Linking converted sales rows to the masters.** Batches still store the names
  as read from the file (cleaned). Mapping them to `CUSTOMER_ID` / `PRODUCT_ID`
  through the aliases now kept on CUSTOMER_MASTER and PRODUCT_MASTER is the
  natural next step.
* **Customer-name mapping.** Gunjeshwari's names were matched against a
  reference list by hand, with two matches flagged as doubtful at the time.
  Names are cleaned here, not mapped.
