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

SEED = [
    ("Yetichem", 15, "seq", 1, r"PW\.(xlsx|xlsm|xls)$",
     "Cross-tab workbooks. The three PW files are picked out of the zip automatically; "
     "Total columns and Total rows are subtotals and are left out."),
    ("Pharmachem", 10, "file", 1, None,
     "Row-wise invoice sheets. Invoice numbers come from the file, and a SALES RETURN sheet "
     "has its quantities and amounts negated."),
    ("Gunjeshwari", 10, "seq", 1, None,
     "Row-wise sheets, numbered INV - 1 upwards. Customer names are cleaned but not mapped "
     "against a reference list."),
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
