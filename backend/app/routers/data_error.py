"""Data Error: the old system's "Resolve" screen. For a distributor's last
conversion, how many rows came in (sales_row, the "temp" table) against how
many reached the main table, and what is wrong with them.

    GET /api/data-error?distributor_id=…&file_type=invoice|mid

file_type: invoice -> MAPPING_MASTER, mid -> MAPPING_MASTER_MID.

* Records in Temp: sales_row rows of the distributor's last conversion that
  writes that table (any for invoice, a Mid Month Y one for mid). sales_row
  keeps the last conversion only, so this is 0 once another has followed.
* Records in Main: the table's rows for the distributor (DIST_ID) and that
  conversion's month and year.
* Records Not Inserted: Temp less Main, when Temp is more.
* Incomplete in Main: rows without a product, customer or HQ.
* Duplicate Records: rows repeating another's invoice, customer, product,
  quantities and rate; the repeats are counted, not the first of each.
* Sum of Amount in Main: SALES_VALUE summed, in the distributor's currency and
  in INR at the Currency rates in force on the conversion's date.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import models as M, models_master as X
from ..database import get_db
from .masters import rate_on

router = APIRouter(prefix="/api")

TYPES = {"invoice": X.SalesMapping, "mid": X.MidSalesMapping}
DUP_KEY = ("invoice_no", "customer_id", "product_id", "sales_qty", "free_quantity",
           "return_quantity", "rate")


def _row(r) -> dict:
    return {"id": r.id, "invoice_no": r.invoice_no, "customer": r.customer_master_name or r.customer_name,
            "product": r.product_master_name or r.product_name, "hq": r.hq_name,
            "territory": r.territory_name, "sales_qty": r.sales_qty, "free_quantity": r.free_quantity,
            "return_quantity": r.return_quantity, "rate": r.rate, "sales_value": r.sales_value}


@router.get("/data-error")
def data_error(distributor_id: int, file_type: str = "invoice", db: Session = Depends(get_db)):
    d = db.get(M.Distributor, distributor_id)
    if d is None:
        raise HTTPException(404, "No such distributor")
    T = TYPES.get(file_type)
    if T is None:
        raise HTTPException(422, "File Type is Invoice or Mid Month.")
    sel = select(M.Batch).where(M.Batch.distributor_id == d.id)
    if file_type == "mid":
        sel = sel.where(M.Batch.mid_month == "Y")
    b = db.execute(sel.order_by(M.Batch.id.desc())).scalars().first()
    out = {"distributor": d.name, "dist_id": d.dist_id, "table": T.__tablename__,
           "batch_id": None, "month": None, "year": None, "mid_month": None, "as_of": None,
           "temp": 0, "main": 0, "not_inserted": 0, "incomplete": 0, "duplicates": 0,
           "amount": 0.0, "currency": None, "amount_inr": None, "rate_note": None,
           "duplicate_rows": [], "incomplete_rows": []}
    if b is None:
        out["rate_note"] = f"{d.name} has no conversion that writes {T.__tablename__} yet."
        return out
    out.update(batch_id=b.id, month=b.month_name, year=b.year, mid_month=b.mid_month,
               as_of=b.as_of.isoformat())
    out["temp"] = db.execute(select(func.count()).select_from(M.SalesRow)
                             .where(M.SalesRow.batch_id == b.id)).scalar()
    mine = (T.dist_id == d.dist_id, T.month == b.month_name, T.year == b.year)
    out["main"] = db.execute(select(func.count()).select_from(T).where(*mine)).scalar()
    out["not_inserted"] = max(out["temp"] - out["main"], 0)

    bad = or_(T.product_id.is_(None), T.customer_id.is_(None), T.hq_id.is_(None))
    out["incomplete"] = db.execute(select(func.count()).select_from(T).where(*mine, bad)).scalar()
    out["incomplete_rows"] = [_row(r) for r in db.execute(
        select(T).where(*mine, bad).order_by(T.id).limit(100)).scalars()]

    key = [getattr(T, k) for k in DUP_KEY]
    groups = select(*key, func.count().label("n")).where(*mine).group_by(*key) \
        .having(func.count() > 1).subquery()
    out["duplicates"] = int(db.execute(select(func.coalesce(func.sum(groups.c.n - 1), 0))).scalar())
    if out["duplicates"]:
        dup_keys = db.execute(select(*[groups.c[k.key] for k in key]).limit(50)).all()
        rows = []
        for k in dup_keys:
            cond = [(c.is_(None) if v is None else c == v) for c, v in zip(key, k)]
            rows += [_row(r) for r in db.execute(select(T).where(*mine, *cond).order_by(T.id)).scalars()]
        out["duplicate_rows"] = rows[:100]

    amount = float(db.execute(select(func.coalesce(func.sum(T.sales_value), 0)).where(*mine)).scalar())
    out["amount"] = round(amount, 2)
    country = db.get(X.Country, d.country_id) if d.country_id else None
    cur = country.currency_code if country else None
    out["currency"] = cur
    if cur:
        try:
            r = rate_on(db, cur, "INR", b.as_of)
            out["amount_inr"] = round(amount * r["rate"], 2)
            out["rate_note"] = (f"{cur} to INR at {r['rate']} (in force from {r['effective_from']})"
                                if r["via"] != "same" else None)
        except HTTPException as e:
            out["rate_note"] = f"{e.detail} Add it on Currency rates to see the amount in INR."
    else:
        out["rate_note"] = f"{d.name} has no country, so its currency is not known: set it on Distributor/Vendor."
    return out
