"""The AFTER INSERT triggers on sales_row.

Every converted row is copied, as it goes in, into the old system's sales
tables, in their shape:

    MidMonth N (the month that ended)    -> MAPPING_MASTER
    MidMonth Y (the month so far)        -> MAPPING_MASTER and MAPPING_MASTER_MID

i.e. every row reaches MAPPING_MASTER, and a mid-month row MAPPING_MASTER_MID too.

The row carries the master IDs it was matched to (CustomerId, ProductId; the
conversion refuses names it cannot match, see services/name_check.py). From
them the trigger takes:

* the product's brand, and its product group: the SKU's own, else its brand's;
* the customer's territory, HQ for that product group, from
  CUSTOMER_TERR_ASSIGNMENT (the row with the lowest ID where a customer has
  more than one), with their names from Territory, Head Quarter and
  Division/Product Group;
* DIST_ID from the distributor (Distributor/Vendor's DIST_ID).

As in the old data, a return goes in as RETURN_QUANTITY (negative) with
SALES_QTY and FREE_QUANTITY 0; CUSTOMER_NAME and PRODUCT_NAME are the names in
the distributor's file, CUSTOMER_MASTER_NAME and PRODUCT_MASTER_NAME the
masters'; PRODUCT_BRAND_CATEGORY is the brand's REPORTING. SALES_VALUE is the
row's amount.

The same SQL serves MySQL (production) and SQLite (tests). The triggers are
dropped and made again on every start, so a change here reaches the database
with the next deploy.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

NAMES = {"MAPPING_MASTER": "trg_sales_row_to_mapping",
         "MAPPING_MASTER_MID": "trg_sales_row_to_mapping_mid"}

COLUMNS = ["DIST_ID", "PRODUCT_NAME", "PRODUCT_ID", "PRODUCT_GROUP_ID", "RATE", "HQ_ID", "MONTH",
           "YEAR", "TERRITORY_ID", "PRODUCT_BRAND_ID", "DIST_NAME", "SALES_QTY", "SALES_VALUE",
           "CUSTOMER_NAME", "CUSTOMER_MASTER_NAME", "PRODUCT_GROUP_NAME", "HQ_NAME",
           "TERRITORY_NAME", "PRODUCT_BRAND_NAME", "INVOICE_NO", "CUSTOMER_ID", "FREE_QUANTITY",
           "RETURN_QUANTITY", "PRODUCT_MASTER_NAME", "PRODUCT_BRAND_CATEGORY"]

GROUP = "COALESCE(p.PRODUCT_GROUP_ID, b.PRODUCT_GROUP_ID)"
VALUES = [
    "d.DistId", "NEW.ProductName", "NEW.ProductId", GROUP, "NEW.Rate", "a.HQ_ID", "NEW.MonthName",
    "NEW.Year", "a.TERRITORY_ID", "p.PRODUCT_BRAND_ID", "NEW.DistributorName",
    "CASE WHEN NEW.IsReturn = 1 THEN 0 ELSE NEW.Quantity END", "NEW.Amount",
    "NEW.CustomerName", "c.CUSTOMER_NAME", "g.Name", "h.Name", "t.Name", "b.PRODUCT_BRAND_NAME",
    "NEW.InvoiceNo", "NEW.CustomerId",
    "CASE WHEN NEW.IsReturn = 1 THEN 0 ELSE NEW.FreeQuantity END",
    "CASE WHEN NEW.IsReturn = 1 THEN -ABS(NEW.Quantity) ELSE 0 END",
    "p.SAP_PRODUCT_NAME", "b.REPORTING",
]


def insert_sql(table: str, mid: bool, q) -> str:
    cols = ", ".join(q(c) for c in COLUMNS)
    return f"""INSERT INTO {table} ({cols})
SELECT {", ".join(VALUES)}
FROM batch bt
JOIN distributor d ON d.Id = bt.DistributorId
LEFT JOIN PRODUCT_MASTER p ON p.PRODUCT_ID = NEW.ProductId
LEFT JOIN PRODUCT_MASTER_BRAND b ON b.PRODUCT_BRAND_ID = p.PRODUCT_BRAND_ID
LEFT JOIN CUSTOMER_MASTER c ON c.CUSTOMER_ID = NEW.CustomerId
LEFT JOIN CUSTOMER_TERR_ASSIGNMENT a ON a.ID = (
    SELECT MIN(x.ID) FROM CUSTOMER_TERR_ASSIGNMENT x
    WHERE x.CUSTOMER_ID = NEW.CustomerId AND x.PRODUCT_GROUP_ID = {GROUP})
LEFT JOIN md_headquarter h ON h.LegacyId = a.HQ_ID
LEFT JOIN md_territory t ON t.LegacyId = a.TERRITORY_ID
LEFT JOIN md_product_group g ON g.LegacyId = {GROUP}
WHERE bt.Id = NEW.BatchId{" AND NEW.MidMonth = 'Y'" if mid else ""}"""


def statements(dialect: str) -> list[str]:
    q = (lambda c: f"`{c}`") if dialect == "mysql" else (lambda c: f'"{c}"')
    out = []
    for table, name in NAMES.items():
        body = insert_sql(table, table.endswith("_MID"), q)
        out.append(f"DROP TRIGGER IF EXISTS {name}")
        if dialect == "mysql":       # one statement: no BEGIN ... END, so no DELIMITER needed
            out.append(f"CREATE TRIGGER {name} AFTER INSERT ON sales_row FOR EACH ROW {body}")
        else:
            out.append(f"CREATE TRIGGER {name} AFTER INSERT ON sales_row FOR EACH ROW "
                       f"BEGIN {body}; END")
    return out


READY = {"ok": False, "error": None}


def ensure(engine: Engine) -> bool:
    """Make (again) both triggers. On failure the conversion refuses to run,
    since rows would reach sales_row and never MAPPING_MASTER."""
    try:
        with engine.begin() as cx:
            for sql in statements(engine.dialect.name):
                cx.execute(text(sql))
        READY.update(ok=True, error=None)
    except Exception as e:                        # e.g. no TRIGGER privilege
        READY.update(ok=False, error=str(e).splitlines()[0][:300])
    return READY["ok"]
