"""Gunjeshwari: a zip of PDF reports, of which the Batch PDF is the one read."""
import io
import zipfile

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from tests.harness import client as c, Testing, ok, sign_in
from app import models as M
from app.services import seed
from app.services.parse import books_in, read_book

HEAD = ["Party Name", "Item Name", "Batch No", "Qty", "Free", "Amount"]


def _ruled_pdf(rows, repeat_header=True):
    """A ruled table long enough to run onto a second page, its header printed
    again at the top of the second page, as report PDFs do."""
    buf = io.BytesIO()
    t = Table([HEAD] + rows, repeatRows=1 if repeat_header else 0)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4).build([t])
    return buf.getvalue()


def _batch_rows():
    """60 sales lines under 3 item headings, a subtotal after each item, and a
    zero line that is left out. 60 x qty 10 = 600; 60 x 1,250.50 = 75,030."""
    rows = []
    for item in ("PARACETAMOL 500MG TAB", "AMOXY 250 CAP", "ORS SACHET"):
        rows.append(["", item, "", "", "", ""])                     # group heading
        for i in range(20):
            rows.append([f"Medico Pharma No.{i}", "", f"B{i:03d}", "10", "2", "1,250.50"])
        rows.append(["", "Item Total", "", "200", "40", "25,010.00"])  # subtotal
    rows.append(["Zero Stores", "ORS SACHET", "B999", "0", "0", "0"])  # nothing sold
    rows.append(["Grand Total", "", "", "600", "120", "75,030.00"])
    return rows


BATCH = _ruled_pdf(_batch_rows())


def _plain_pdf():
    """A report printed with no lines at all: read from the gaps between words."""
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    xs = [40, 190, 330, 400, 450, 500]
    y = 800
    for row in [HEAD, ["Shree Medical", "CETRIZINE TAB", "C01", "5", "0", "500.00"],
                ["Om Pharmacy", "CETRIZINE TAB", "C02", "7", "1", "700.00"]]:
        for x, v in zip(xs, row):
            cv.drawString(x, y, v)
        y -= 18
    cv.save()
    return buf.getvalue()


def _no_table_pdf():
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.drawString(72, 750, "Monthly summary - see attached batch report.")
    cv.save()
    return buf.getvalue()


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


ZIPPED = _zip({"Gunjeshwari/Sales Batch Wise Report.pdf": BATCH,
               "Gunjeshwari/Item Wise Summary.pdf": _plain_pdf(),
               "Gunjeshwari/Cover note.pdf": _no_table_pdf(),
               "__MACOSX/Gunjeshwari/._Sales Batch Wise Report.pdf": b"junk"})


@pytest.fixture(scope="module")
def tok():
    return sign_in()


def H(t):
    return {"Authorization": f"Bearer {t}"}


def gunj(tok):
    return [d for d in ok(c.get("/api/distributors", headers=H(tok)))
            if d["name"] == "Gunjeshwari"][0]


# ================================================================ the parser
def test_a_zip_now_offers_its_pdfs():
    names = [n for n, _ in books_in("gunj.zip", ZIPPED)]
    assert names == ["Cover note.pdf", "Item Wise Summary.pdf", "Sales Batch Wise Report.pdf"]


def test_the_batch_pdf_is_read_across_pages_with_headings_filled_down():
    r = read_book("Sales Batch Wise Report.pdf", BATCH)
    assert r["error"] is None
    assert len(r["rows"]) == 60 and r["omitted"] == 1
    assert sum(x["qty"] for x in r["rows"]) == 600
    assert round(sum(x["amount"] for x in r["rows"]), 2) == 75030.00
    assert sum(x["free"] for x in r["rows"]) == 120
    # every line carries the item printed once above it, never a subtotal's label
    assert {x["product"] for x in r["rows"]} == {"PARACETAMOL 500MG TAB", "AMOXY 250 CAP",
                                                  "ORS SACHET"}
    assert r["rows"][0]["customer"] == "Medico Pharma No 0"
    assert "from PDF" in r["sheets"][0]["layout"] and "2 pages" in r["sheets"][0]["name"]


def test_a_pdf_without_ruled_lines_is_still_read():
    r = read_book("Item Wise Summary.pdf", _plain_pdf())
    assert r["error"] is None, r
    assert [(x["customer"], x["qty"], x["amount"]) for x in r["rows"]] == [
        ("Shree Medical", 5.0, 500.0), ("Om Pharmacy", 7.0, 700.0)]


def test_a_pdf_with_no_table_is_refused_with_a_reason():
    r = read_book("Cover note.pdf", _no_table_pdf())
    assert r["rows"] == [] and "PDF" in r["error"]


def test_a_broken_pdf_is_refused_not_crashed():
    r = read_book("broken.pdf", b"%PDF-1.4 not really")
    assert r["rows"] == [] and r["error"]


# ===================================================== the rule and the screen
def test_gunjeshwari_picks_the_batch_pdf(tok):
    d = gunj(tok)
    assert d["pick_pattern"] and "batch" in d["pick_pattern"].lower()
    r = ok(c.post("/api/uploads/inspect", headers=H(tok),
                  files=[("files", ("gunj.zip", ZIPPED, "application/zip"))],
                  data={"distributor_id": str(d["id"])}))
    by = {f["name"]: f for f in r["files"]}
    assert set(by) == {"Cover note.pdf", "Item Wise Summary.pdf", "Sales Batch Wise Report.pdf"}
    assert [n for n, f in by.items() if f["suggested"]] == ["Sales Batch Wise Report.pdf"]
    assert by["Sales Batch Wise Report.pdf"]["rows"] == 60
    assert by["Cover note.pdf"]["error"]

    b = ok(c.post(f"/api/uploads/{r['token']}/commit", headers=H(tok), json={
        "distributor_id": d["id"], "as_of": "2026-10-05",
        "files": ["Sales Batch Wise Report.pdf"], "source": r["source"]}))
    assert b["rows"] == 60 and b["total_qty"] == 600 and b["total_amount"] == 75030.00
    assert (b["month"], b["mid_month"]) == ("September", "N")       # 5th, cut-off 10th

    got = ok(c.get(f"/api/batches/{b['batch_id']}", headers=H(tok)))
    used = {f["name"]: f["used"] for f in got["files"]}
    assert used == {"Sales Batch Wise Report.pdf": True, "Item Wise Summary.pdf": False,
                    "Cover note.pdf": False}
    rows = ok(c.get(f"/api/batches/{b['batch_id']}/rows?size=5", headers=H(tok)))["rows"]
    assert rows[0]["invoice_no"] == "INV - 1"
    assert rows[0]["source_file"] == "Sales Batch Wise Report.pdf"
    assert rows[0]["distributor_name"] == "Gunjeshwari"


def test_an_old_database_is_brought_forward_but_a_typed_rule_is_kept():
    db = Testing()
    try:
        d = db.query(M.Distributor).filter_by(name="Gunjeshwari").one()
        keep = (d.pick_pattern, d.note)
        d.pick_pattern, d.note = None, seed._GUNJESHWARI_OLD_NOTE
        db.commit()
        seed.update_rules(db)
        assert d.pick_pattern == seed.GUNJESHWARI_PICK and d.note == seed.GUNJESHWARI_NOTE

        d.pick_pattern, d.note = r"BATCH_REPORT\.pdf$", "typed by hand"
        db.commit()
        seed.update_rules(db)
        assert (d.pick_pattern, d.note) == (r"BATCH_REPORT\.pdf$", "typed by hand")
        d.pick_pattern, d.note = keep
        db.commit()
    finally:
        db.close()
