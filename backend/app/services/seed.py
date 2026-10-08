"""The three distributors and the rules they arrived with.

A function rather than code at import time, so the same seeding runs against
the real database at startup and against the test database in the tests —
otherwise the tests exercise an empty table that production never has.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import date

from .. import models as M
from .. import models_master as X

# Gunjeshwari's rule, as given (replaces the earlier Gunjeshwari rule).
# Two zip files are uploaded together; the files to convert are the ones named
# ALI BATCHWISE*.pdf and AHL BATCHWISE*.pdf extracted from them, combined into
# one twelve-column sheet.
GUNJESHWARI_PICK = r"(ail|ali|ahl|ahpl)[^/]*batch\s*wise[^/]*\.pdf$"
GUNJESHWARI_NOTE = ("Zips uploaded together: the SALES BATCHWISE PDFs (AIL, AHPL, ALI or AHL) are "
                    "picked and combined into one sheet, numbered INV - 1 upwards. Month/Mid Month: "
                    "1st-10th = previous month, N; else current month, Y. The 'Sales Challan "
                    "Analysis' report is read line by line: customer from 'Sh. Name', product, "
                    "Quantity, Free, Rate and Amount (= B.Amount) from each batch line. Customer "
                    "and product names replaced from the Excel lists where they match, ignoring "
                    "special characters.")
# Earlier seeded notes and pick patterns. One still reading a seeded default
# was never edited by hand, so it is brought forward; anything else is kept.
_GUNJESHWARI_OLD_NOTES = (
    "Row-wise sheets, numbered INV - 1 upwards. Customer names are cleaned but not mapped "
    "against a reference list.",
    "Zip of PDF reports: the PDF with Batch in its name is picked and its table read. "
    "Numbered INV - 1 upwards; customer names are cleaned but not mapped.",
    "Zip with ALI BATCHWISE.pdf and AHL BATCHWISE.pdf: every PDF with Batch in its "
    "name is picked and combined into one sheet, numbered INV - 1 upwards across both. "
    "Quantity, Free Quantity, Rate and Amount (= B.Amount) are read from the PDF; a "
    "product repeated on lines starting with a quantity becomes one row per line. "
    "Customer and product names are replaced from the reference lists where they "
    "match, ignoring special characters.",
    "Two zips uploaded together: the ALI BATCHWISE*.pdf and AHL BATCHWISE*.pdf files "
    "extracted from them are picked and combined into one sheet, numbered INV - 1 "
    "upwards. Month/Mid Month: 1st-10th = previous month, N; else current month, Y. "
    "Quantity, Free Quantity, Rate and Amount (= B.Amount) from the PDF; a product "
    "repeated from the quantity is its own row. Customer and product names replaced "
    "from the Excel lists where they match, ignoring special characters.")

_GUNJESHWARI_OLD_NOTE = _GUNJESHWARI_OLD_NOTES[0]
_GUNJESHWARI_OLD_PICKS = (r"batch[^/]*\.pdf$", r"(ali|ahl)\s*batch\s*wise[^/]*\.pdf$")
RATE_FROM_FILE = {"Gunjeshwari"}
# Distributors whose files are chosen by hand under all conditions: every file
# extracted from the zip is offered and can be ticked, whatever its name, type
# or whether the strict reader understood it, and a ticked file is read (more
# loosely if need be) under the distributor's rules. The ALI/AHL BATCHWISE pattern above
# then only decides what is ticked to begin with; the person's choice wins.
SELECT_ANY = {"Gunjeshwari"}

# Yetichem sends a zip with three cross-tab workbooks, AHCPW.xls, AILGPW.xls
# and AILNPW.xls; the PW pattern picks all three and they become one sheet.
YETICHEM_NOTE = ("Zip with AHCPW.xls, AILGPW.xls and AILNPW.xls: the three PW workbooks are picked "
                 "and combined into one sheet, numbered INV - 1 upwards across all three. Quantity "
                 "and Free Quantity come from cells like 40 + 0; a negative quantity (-40 + 0) is kept "
                 "as -40. Rate is Amount / Quantity; B.Amount = Amount, from the file. Rows with "
                 "quantity and free both 0, and Total rows and columns, are left out.")
_YETICHEM_OLD_NOTES = (
    "Cross-tab workbooks. The three PW files are picked out of the zip automatically; "
    "Total columns and Total rows are subtotals and are left out.",)

SEED = [
    ("Yetichem", 15, "seq", 1, r"PW\.(xlsx|xlsm|xls)$", YETICHEM_NOTE),
    ("Pharmachem", 10, "file", 1, None,
     "Row-wise invoice sheets. Invoice numbers come from the file, and a SALES RETURN sheet "
     "has its quantities and amounts negated."),
    ("Gunjeshwari", 10, "seq", 1, GUNJESHWARI_PICK, GUNJESHWARI_NOTE),
]


def ensure(db: Session) -> None:
    """Add any distributor that is missing. Never edits one that is there, so a
    cut-off corrected on screen is not undone by the next restart."""
    for name, cut, mode, neg, pick, note in SEED:
        if db.execute(select(M.Distributor)
                      .where(M.Distributor.name == name)).scalar_one_or_none():
            continue
        db.add(M.Distributor(name=name, cutoff_day=cut, invoice_mode=mode,
                             negate_returns=neg, pick_pattern=pick, note=note,
                             rate_mode="file" if name in RATE_FROM_FILE else "calc"))
    db.commit()


def update_rules(db: Session) -> list[str]:
    """Bring a seeded rule forward when the way a distributor sends its files
    changes - but only while it is still on the old default. A pattern or note
    somebody typed on the Rules screen is left exactly as it is."""
    done = []
    y = db.execute(select(M.Distributor)
                   .where(M.Distributor.name == "Yetichem")).scalar_one_or_none()
    if y is not None and y.note in _YETICHEM_OLD_NOTES:
        y.note = YETICHEM_NOTE
        done.append("Yetichem's rule description brought up to date")
    d = db.execute(select(M.Distributor)
                   .where(M.Distributor.name == "Gunjeshwari")).scalar_one_or_none()
    if d is not None:
        if not d.pick_pattern or d.pick_pattern in _GUNJESHWARI_OLD_PICKS:
            d.pick_pattern = GUNJESHWARI_PICK
            done.append("Gunjeshwari now picks ALI BATCHWISE*.pdf and AHL BATCHWISE*.pdf")
        if d.note in _GUNJESHWARI_OLD_NOTES:
            # still on a seeded default, so the newer rules come with it:
            # the new description, and Rate read from the file
            d.note = GUNJESHWARI_NOTE
            d.rate_mode = "file"
            done.append("Gunjeshwari's rule replaced with the current one (Rate from the file)")
    db.commit()
    return done


# The two countries the distributors sell in, and the rate between their
# currencies. The Nepali rupee is pegged at 1.60 to the Indian rupee; it is
# seeded as a starting point and is edited on the Currency rates screen.
COUNTRIES = [("IN", "India", "INR"), ("NP", "Nepal", "NPR")]
RATE = ("INR", "NPR", 1.6, date(2000, 1, 1), "Official peg; confirm before relying on it")


def ensure_masters(db: Session) -> None:
    """Same rule as the distributors: add what is missing, never edit."""
    for code, name, cur in COUNTRIES:
        if not db.execute(select(X.Country).where(X.Country.code == code)).scalar_one_or_none():
            db.add(X.Country(code=code, name=name, currency_code=cur, active=1))
    db.flush()
    a, b, rate, eff, note = RATE
    have = db.execute(select(X.CurrencyRate.id).where(
        ((X.CurrencyRate.from_currency == a) & (X.CurrencyRate.to_currency == b)) |
        ((X.CurrencyRate.from_currency == b) & (X.CurrencyRate.to_currency == a)))).first()
    if not have:
        db.add(X.CurrencyRate(from_currency=a, to_currency=b, rate=rate,
                              effective_from=eff, note=note))
    db.commit()
