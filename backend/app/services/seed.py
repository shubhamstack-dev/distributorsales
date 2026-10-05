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

# Gunjeshwari sends a zip of PDF reports; the one to convert has "Batch" in its
# name (the batch-wise sales report).
GUNJESHWARI_PICK = r"batch[^/]*\.pdf$"
GUNJESHWARI_NOTE = ("Zip of PDF reports: the PDF with Batch in its name is picked and its table "
                    "read. Numbered INV - 1 upwards; customer names are cleaned but not mapped.")
_GUNJESHWARI_OLD_NOTE = ("Row-wise sheets, numbered INV - 1 upwards. Customer names are cleaned "
                         "but not mapped against a reference list.")

SEED = [
    ("Yetichem", 15, "seq", 1, r"PW\.(xlsx|xlsm|xls)$",
     "Cross-tab workbooks. The three PW files are picked out of the zip automatically; "
     "Total columns and Total rows are subtotals and are left out."),
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
                             negate_returns=neg, pick_pattern=pick, note=note))
    db.commit()


def update_rules(db: Session) -> list[str]:
    """Bring a seeded rule forward when the way a distributor sends its files
    changes - but only while it is still on the old default. A pattern or note
    somebody typed on the Rules screen is left exactly as it is."""
    done = []
    d = db.execute(select(M.Distributor)
                   .where(M.Distributor.name == "Gunjeshwari")).scalar_one_or_none()
    if d is not None:
        if not d.pick_pattern:
            d.pick_pattern = GUNJESHWARI_PICK
            done.append("Gunjeshwari now picks the Batch PDF")
        if d.note == _GUNJESHWARI_OLD_NOTE:
            d.note = GUNJESHWARI_NOTE
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
