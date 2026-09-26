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

    cd backend && pytest -q        # 27 tests

They cover the gate (every route is walked without a token and must refuse),
the month rule across the year and both cut-offs, the parser against the real
workbooks, and the whole journey — inspect, commit, read back, export — with the
totals checked at each step. The suite asserts the numbers this replaced:
**82 rows, 140 omitted, 43,200 quantity, 27,65,117.77**.

## What it does not do

* **PDFs.** Gunjeshwari and Pharmachem originally arrived as PDFs. Extracting
  tables from them is unreliable enough that refusing beats handing over
  plausible-looking wrong numbers. Export to Excel first.
* **Customer-name mapping.** Gunjeshwari's names were matched against a
  reference list by hand, with two matches flagged as doubtful at the time.
  Names are cleaned here, not mapped.
