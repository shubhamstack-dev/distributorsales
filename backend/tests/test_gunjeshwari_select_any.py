"""Gunjeshwari: every file extracted from the zip can be chosen, under all
conditions, and the chosen file is read under Gunjeshwari's rules - even when
its name has no Batch in it and its header is not in the usual words."""
import io
import zipfile

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from tests.harness import client as c, ok, sign_in
from app.services.parse import books_in, read_book


def _ruled(rows):
    buf = io.BytesIO()
    t = Table(rows, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4).build([t])
    return buf.getvalue()


# Header in other words: A/c Name, Description, Sale Qty, Sch, PTR, Value.
OTHER_WORDS = _ruled([
    ["A/c Name", "Description", "Sale Qty", "Sch", "PTR", "Value"],
    ["Shree Medical", "CETRIZINE TAB", "5", "1", "10.00", "50.00"],
    ["Om Pharmacy", "CETRIZINE TAB", "7", "0", "10.00", "70.00"],
    ["Grand Total", "", "12", "1", "", "120.00"],
])

# No customer column: the party is a heading line, no Amount column either.
PARTY_HEADINGS = _ruled([
    ["Item Name", "Batch", "Qty", "Free", "Rate"],
    ["Party Name : NEW HOPE CLINIC", "", "", "", ""],
    ["ORS SACHET", "OR9", "4", "0", "8.25"],
    ["", "OR10", "2", "0", "8.25"],                  # same product, another batch
    ["Party Name : CITY CHEMIST", "", "", "", ""],
    ["AMOXY 250 CAP", "AX01", "3", "1", "40.00"],
    ["Total", "", "9", "1", ""],
])


def _text_only():
    """No table and no ruled lines: a party line, then item lines ending in figures."""
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in ["GUNJESHWARI PHARMA - SALES REGISTER",
               "Item Batch Qty Free Rate Amount",
               "Party: SHREE MEDICAL HALL",
               "PARACETAMOL 500 TAB PB01 10 2 12.50 125.00",
               "PB02 4 0 12.50 50.00",
               "Item Total 14 2 175.00",
               "Party: OM PHARMACY",
               "ORS SACHET OR9 20 0 8.25 165.00",
               "Grand Total 34 2 340.00"]:
        cv.drawString(40, y, ln)
        y -= 16
    cv.save()
    return buf.getvalue()


TEXT_ONLY = _text_only()
CSV = b"Party,Product,Qty,Free,Rate,Amount\nSHREE MEDICAL,DOLO 650,10,0,30,300\n"


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


INNER = _zip({"Inner Sales.pdf": OTHER_WORDS})
ZIPPED = _zip({
    "Gunjeshwari/ALI BATCHWISE.pdf": OTHER_WORDS,
    "Gunjeshwari/Sales Register.pdf": OTHER_WORDS,
    "Gunjeshwari/Party Wise.pdf": PARTY_HEADINGS,
    "Gunjeshwari/Register text.pdf": TEXT_ONLY,
    "Gunjeshwari/sales.csv": CSV,
    "Gunjeshwari/readme.docx": b"PK\x03\x04 not a real document",
    "Gunjeshwari/_hidden summary.pdf": OTHER_WORDS,
    "Other folder/Sales Register.pdf": PARTY_HEADINGS,  # same name, other folder
    "Gunjeshwari/more.zip": INNER,
    "__MACOSX/Gunjeshwari/._ALI BATCHWISE.pdf": b"junk",
})


@pytest.fixture(scope="module")
def tok():
    return sign_in()


def H(t):
    return {"Authorization": f"Bearer {t}"}


def dist(tok, name):
    return [d for d in ok(c.get("/api/distributors", headers=H(tok))) if d["name"] == name][0]


# ================================================================ extraction
def test_every_file_in_the_zip_is_offered():
    names = sorted(n for n, _ in books_in("g.zip", ZIPPED, everything=True))
    assert names == sorted([
        "ALI BATCHWISE.pdf", "Sales Register.pdf", "Sales Register (2).pdf", "Party Wise.pdf",
        "Register text.pdf", "sales.csv", "readme.docx", "_hidden summary.pdf",
        "Inner Sales.pdf"])
    # the strict listing for other distributors is unchanged
    assert "readme.docx" not in [n for n, _ in books_in("g.zip", ZIPPED)]


def test_a_header_in_other_words_is_read():
    r = read_book("Sales Register.pdf", OTHER_WORDS, any_file=True)
    assert r["error"] is None
    assert [(x["customer"], x["product"], x["qty"], x["free"], x["rate"], x["amount"])
            for x in r["rows"]] == [("Shree Medical", "CETRIZINE TAB", 5, 1, 10.0, 50.0),
                                    ("Om Pharmacy", "CETRIZINE TAB", 7, 0, 10.0, 70.0)]


def test_party_headings_fill_the_customer_and_amount_is_qty_x_rate():
    r = read_book("Party Wise.pdf", PARTY_HEADINGS, any_file=True)
    assert r["error"] is None
    assert [(x["customer"], x["product"], x["qty"], x["amount"]) for x in r["rows"]] == [
        ("NEW HOPE CLINIC", "ORS SACHET", 4, 33.0),
        ("NEW HOPE CLINIC", "ORS SACHET", 2, 16.5),
        ("CITY CHEMIST", "AMOXY 250 CAP", 3, 120.0)]


def test_a_pdf_with_no_table_is_read_line_by_line():
    r = read_book("Register text.pdf", TEXT_ONLY, any_file=True)
    assert r["error"] is None, r
    assert [(x["customer"], x["product"], x["qty"], x["free"], x["rate"], x["amount"])
            for x in r["rows"]] == [
        ("SHREE MEDICAL HALL", "PARACETAMOL 500 TAB", 10, 2, 12.5, 125.0),
        ("SHREE MEDICAL HALL", "PARACETAMOL 500 TAB", 4, 0, 12.5, 50.0),
        ("OM PHARMACY", "ORS SACHET", 20, 0, 8.25, 165.0)]


def test_a_csv_is_read():
    r = read_book("sales.csv", CSV, any_file=True)
    assert [(x["customer"], x["qty"], x["amount"]) for x in r["rows"]] == [
        ("SHREE MEDICAL", 10, 300)]


def test_a_file_with_nothing_in_it_says_so_but_does_not_crash():
    r = read_book("readme.docx", b"PK\x03\x04 nope", any_file=True)
    assert r["rows"] == [] and r["error"]


# ===================================================== the screen and the batch
def test_gunjeshwari_offers_every_file_as_selectable(tok):
    g = dist(tok, "Gunjeshwari")
    assert g["select_any"] is True
    assert dist(tok, "Yetichem")["select_any"] is False
    r = ok(c.post("/api/uploads/inspect", headers=H(tok),
                  files=[("files", ("g.zip", ZIPPED, "application/zip"))],
                  data={"distributor_id": str(g["id"])}))
    by = {f["name"]: f for f in r["files"]}
    assert len(by) == 9 and all(f["selectable"] for f in by.values())
    assert by["readme.docx"]["error"]                    # unreadable, still selectable
    assert [n for n, f in by.items() if f["suggested"]] == ["ALI BATCHWISE.pdf"]


def test_a_hand_picked_file_without_batch_in_its_name_is_converted(tok):
    g = dist(tok, "Gunjeshwari")
    r = ok(c.post("/api/uploads/inspect", headers=H(tok),
                  files=[("files", ("g.zip", ZIPPED, "application/zip"))],
                  data={"distributor_id": str(g["id"])}))
    picked = ["Party Wise.pdf", "Register text.pdf", "readme.docx"]
    b = ok(c.post(f"/api/uploads/{r['token']}/commit", headers=H(tok), json={
        "distributor_id": g["id"], "as_of": "2026-10-05", "files": picked,
        "source": r["source"]}))
    assert b["rows"] == 6
    assert (b["month"], b["year"], b["mid_month"]) == ("September", 2026, "N")
    got = ok(c.get(f"/api/batches/{b['batch_id']}", headers=H(tok)))
    assert {f["name"] for f in got["files"] if f["used"]} == set(picked)
    assert "readme.docx" in got["notes"]                  # chosen, nothing in it
    rows = ok(c.get(f"/api/batches/{b['batch_id']}/rows", headers=H(tok)))["rows"]
    assert [x["invoice_no"] for x in rows] == [f"INV - {i}" for i in range(1, 7)]
    assert all(x["distributor_name"] == "Gunjeshwari" for x in rows)
    assert rows[0]["rate"] == 8.25                        # Rate read from the file


def test_choosing_only_an_unreadable_file_names_it(tok):
    g = dist(tok, "Gunjeshwari")
    r = ok(c.post("/api/uploads/inspect", headers=H(tok),
                  files=[("files", ("g.zip", ZIPPED, "application/zip"))],
                  data={"distributor_id": str(g["id"])}))
    x = c.post(f"/api/uploads/{r['token']}/commit", headers=H(tok), json={
        "distributor_id": g["id"], "as_of": "2026-10-05", "files": ["readme.docx"]})
    assert x.status_code == 409 and "readme.docx" in x.json()["detail"]
