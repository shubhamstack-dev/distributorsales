"""Yetichem end to end: three cross-tab .xls workbooks (AHCPW.xls, AILGPW.xls,
AILNPW.xls) combined into the twelve-column sheet."""
import io
import zipfile

import pytest

from tests.harness import client as c, Testing, ok, sign_in
from app import models as M
from app.services import seed
from app.services.parse import read_book

xlwt = pytest.importorskip("xlwt")       # writes the old .xls format for the tests


def _xls(customers, products):
    """The cross-tab: products down, customers across, 'qty + free' on one row
    and the amounts on the row below. Sn is a number, as Excel stores it."""
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    head = ["Sn", "Code", "Pack", "Prodname", "Unit"] + customers + ["Total"]
    for i, h in enumerate(head):
        ws.write(2, i, h)
    r = 3
    for prod, cells in products:
        ws.write(r, 0, 1)
        ws.write(r, 3, prod)
        for j, (q, amt) in enumerate(cells):
            if q is not None:
                ws.write(r, 5 + j, q)
                ws.write(r + 1, 5 + j, amt)
        ws.write(r, 5 + len(customers), "999 + 0")          # Total column: ignored
        r += 2
    ws.write(r, 0, 1)
    ws.write(r, 3, "Total")                                  # Total row: ignored
    ws.write(r, 5, "999 + 0")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


AHC = _xls(["Rantoks Pharma Pvt.ltd.", "Om Medicals"], [
    ("STEMETIL 5MG TAB", [("40 + 0", 4000), ("0 + 0", 0)]),       # second cell omitted
    ("PAN-40 TAB", [("- 40 + 0", -2000), ("10 + 2", 500)]),        # a return, kept
])
AILG = _xls(["Shree Pharmacy"], [("ORS SACHET", [("-5+0", -250)])])
AILN = _xls(["Om Medicals"], [("CETRIZINE TAB", [("0 + 3", 0)])])  # free only, kept
ZIPPED = io.BytesIO()
with zipfile.ZipFile(ZIPPED, "w") as z:
    for n, d in [("AHCPW.xls", AHC), ("AILGPW.xls", AILG), ("AILNPW.xls", AILN),
                 ("AHCSTOCKS.xls", AHC)]:
        z.writestr(f"MID-MONTH/{n}", d)
ZIPPED = ZIPPED.getvalue()


@pytest.fixture(scope="module")
def tok():
    return sign_in()


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def yeti(tok):
    return [d for d in ok(c.get("/api/distributors", headers=H(tok)))
            if d["name"] == "Yetichem"][0]


def test_an_xls_cross_tab_is_read():
    r = read_book("AHCPW.xls", AHC)
    assert r["error"] is None and r["sheets"][0]["layout"] == "cross-tab"
    got = [(x["customer"], x["product"], x["qty"], x["free"], x["amount"]) for x in r["rows"]]
    assert got == [("Rantoks Pharma Pvt ltd", "STEMETIL 5MG TAB", 40, 0, 4000),
                   ("Rantoks Pharma Pvt ltd", "PAN 40 TAB", -40, 0, -2000),
                   ("Om Medicals", "PAN 40 TAB", 10, 2, 500)]
    assert r["omitted"] == 1                      # the 0 + 0 cell


def commit(tok, yeti, as_of):
    r = ok(c.post("/api/uploads/inspect", headers=H(tok),
                  files=[("files", ("FW__MID-MONTH_SALES.zip", ZIPPED, "application/zip"))],
                  data={"distributor_id": str(yeti["id"])}))
    picked = sorted(f["name"] for f in r["files"] if f["suggested"])
    assert picked == ["AHCPW.xls", "AILGPW.xls", "AILNPW.xls"]      # not the stocks file
    b = ok(c.post(f"/api/uploads/{r['token']}/commit", headers=H(tok), json={
        "distributor_id": yeti["id"], "as_of": as_of, "files": picked, "source": r["source"]}))
    rows = ok(c.get(f"/api/batches/{b['batch_id']}/rows?size=50", headers=H(tok)))["rows"]
    return b, rows


def test_the_three_workbooks_become_one_sheet(tok, yeti):
    b, rows = commit(tok, yeti, "2026-10-15")
    assert b["rows"] == 5 and b["omitted"] == 1
    assert [r["invoice_no"] for r in rows] == [f"INV - {i}" for i in range(1, 6)]
    assert all(r["distributor_name"] == "Yetichem" for r in rows)
    # uploaded on the 15th: on or before the cut-off, so last month and N
    assert {(r["month"], r["year"], r["mid_month"]) for r in rows} == {("September", 2026, "N")}
    assert b["total_qty"] == 40 - 40 + 10 - 5 + 0


def test_negative_quantities_are_kept_and_rate_is_amount_over_quantity(tok, yeti):
    _, rows = commit(tok, yeti, "2026-10-16")
    by = {(r["customer_name"], r["product_name"]): r for r in rows}
    neg = by[("Rantoks Pharma Pvt ltd", "PAN 40 TAB")]
    assert (neg["quantity"], neg["free_quantity"], neg["amount"], neg["rate"]) == (-40, 0, -2000, 50)
    assert by[("Shree Pharmacy", "ORS SACHET")]["quantity"] == -5
    assert by[("Om Medicals", "CETRIZINE TAB")]["rate"] == 0          # free only: no division by 0
    assert all(r["b_amount"] == r["amount"] for r in rows)
    assert {(r["month"], r["mid_month"]) for r in rows} == {("October", "Y")}


def test_an_old_database_gets_the_new_description():
    db = Testing()
    try:
        d = db.query(M.Distributor).filter_by(name="Yetichem").one()
        keep = d.note
        d.note = seed._YETICHEM_OLD_NOTES[0]
        db.commit()
        seed.update_rules(db)
        assert d.note == seed.YETICHEM_NOTE
        d.note = "typed by hand"
        db.commit()
        seed.update_rules(db)
        assert d.note == "typed by hand"
        d.note = keep
        db.commit()
    finally:
        db.close()
