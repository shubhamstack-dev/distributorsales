"""The three distributors and the rules they arrived with.

A function rather than code at import time, so the same seeding runs against
the real database at startup and against the test database in the tests —
otherwise the tests exercise an empty table that production never has.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M

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
