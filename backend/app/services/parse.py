"""Reading the distributors' workbooks, and the PDF reports some of them send.

Two layouts turn up. A cross-tab - products down the page, customers across,
quantities on one row and amounts on the next - and a plain row-wise sheet with
a header naming its columns. Which one a file uses is worked out from the file,
not from its name, because the names are not reliable.

A PDF is read the same way once its tables are lifted out: every table on every
page is joined into one list of rows, a header repeated at the top of each page
is dropped, and the rows go through the same two layouts. Report PDFs often
print the item (or the party) once as a group heading and leave it blank on the
lines below, so in a PDF a blank product or customer takes the one above it.
"""
from __future__ import annotations

import io
import re
import zipfile

from openpyxl import load_workbook

# "40 + 0" is 40 bought and 0 free. A minus may be written apart from the
# figure ("- 40 + 0"); it stays with it, so that is -40 bought.
QTY = re.compile(r"^\s*(-?\s*[\d.,]+)\s*\+\s*(-?\s*[\d.,]+)\s*$")
BOOK = re.compile(r"\.(xlsx|xlsm|xls)$", re.I)
PDF = re.compile(r"\.pdf$", re.I)

WANT = {
    "customer": ["customername", "customer", "party", "partyname", "shopname"],
    "product": ["productname", "product", "item", "itemname", "particulars", "prodname",
                "itemdescription", "productdescription"],
    "qty": ["quantity", "qty"],
    "free": ["freequantity", "freeqty", "free", "fqty"],
    "amount": ["amount", "netamount", "value", "bamount", "basicamount"],
    "invoice": ["invoiceno", "invoicenumber", "invno", "billno", "invoice"],
    "rate": ["rate", "salerate", "salesrate", "unitrate", "ptr"],
}


def clean(s) -> str:
    """Drop special characters. Punctuation becomes a space rather than nothing,
    so 'Rantoks Pharma Pvt.ltd.' reads 'Rantoks Pharma Pvt ltd', not 'Pvtltd'."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]+", " ", str(s if s is not None else ""))).strip()


def _norm(s) -> str:
    return re.sub(r"[^a-z]", "", str(s if s is not None else "").lower())


def _num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(re.sub(r"[\s,]", "", str(v if v is not None else "")))
    except ValueError:
        return 0.0


def readable(name: str) -> bool:
    return bool(BOOK.search(name) or PDF.search(name))


def books_in(name: str, data: bytes):
    """Whatever was uploaded, reduced to the files this can read: a zip is
    opened, and the workbooks and PDFs inside it - or sent loose - are taken
    as they are. Anything else is left out."""
    if name.lower().endswith(".zip"):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                inner = info.filename
                if info.is_dir() or inner.startswith("__MACOSX/") or not readable(inner):
                    continue
                base = inner.split("/")[-1]
                if base.startswith(".") or base.startswith("_"):
                    continue
                out.append((base, z.read(info)))
        return out
    if readable(name):
        return [(name.split("/")[-1], data)]
    return []


def _cross_tab_header(rows) -> int:
    for r in range(min(len(rows), 25)):
        cells = [_norm(c) for c in (rows[r] or [])[:6]]
        if "prodname" in cells and "sn" in cells and "unit" in cells:
            return r
    return -1


def _parse_cross_tab(rows, hr, out, stats):
    head = rows[hr]
    cols = [c for c in range(5, len(head))
            if head[c] is not None and str(head[c]).strip() and _norm(head[c]) != "total"]
    r = hr + 1
    while r < len(rows):
        row = rows[r]
        sn = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ""
        prod = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ""
        if sn != "1" or not prod or _norm(prod) == "total":
            r += 1
            continue
        amounts = rows[r + 1] if r + 1 < len(rows) else []
        for c in cols:
            cell = row[c] if c < len(row) else None
            m = QTY.match(str(cell if cell is not None else ""))
            if not m:
                continue
            q, f = _num(m.group(1)), _num(m.group(2))
            if q == 0 and f == 0:            # nothing bought and nothing given
                stats["omitted"] += 1
                continue
            amt = _num(amounts[c]) if c < len(amounts) else 0.0
            out.append({"customer": clean(head[c]), "product": clean(prod),
                        "qty": q, "free": f, "amount": amt, "invoice": None, "rate": None,
                        "is_return": False})
        r += 2                               # the amount row has been consumed
    return "cross-tab"


def _map_columns(rows):
    for r in range(min(len(rows), 30)):
        cells = [_norm(c) for c in (rows[r] or [])]
        found = {}
        for key, names in WANT.items():
            for i, c in enumerate(cells):
                if c and c in names:
                    found[key] = i
                    break
        if all(k in found for k in ("customer", "product", "qty", "amount")):
            return r, found
    return None


def _parse_row_wise(rows, hr, cmap, out, stats, is_return, negate, fill_down=False):
    sign = -1 if (is_return and negate) else 1
    last = {"customer": "", "product": ""}
    for r in range(hr + 1, len(rows)):
        row = rows[r]

        def get(k):
            return row[cmap[k]] if k in cmap and cmap[k] < len(row) else None

        cust = str(get("customer") or "").strip()
        prod = str(get("product") or "").strip()
        if fill_down:
            # a group heading row (item or party alone, no figures) only sets
            # what the lines below it belong to
            if (cust or prod) and get("qty") in (None, "") and get("amount") in (None, ""):
                if cust:
                    last["customer"] = cust
                if prod:
                    last["product"] = prod
                continue
            if not cust and not prod:
                # A line with figures but no names is either the same product
                # carried on to another batch (it starts from the quantity, and
                # carries a rate) or a subtotal (no rate). Only the first is a sale.
                if get("rate") in (None, "") or not (last["customer"] or last["product"]):
                    continue
            if _norm(cust).endswith("total") or _norm(prod).endswith("total"):
                continue
            cust = cust or last["customer"]
            prod = prod or last["product"]
            last["customer"], last["product"] = cust, prod
        if not cust and not prod:
            continue
        if _norm(cust) in ("total", "grandtotal") or _norm(prod) in ("total", "grandtotal"):
            continue
        m = QTY.match(str(get("qty") or ""))
        if m:
            q, f = _num(m.group(1)), _num(m.group(2))
        else:
            q, f = _num(get("qty")), _num(get("free"))
        if q == 0 and f == 0:
            stats["omitted"] += 1
            continue
        inv = get("invoice")
        rate = get("rate")
        out.append({"customer": clean(cust), "product": clean(prod),
                    "qty": q * sign, "free": f * sign, "amount": _num(get("amount")) * sign,
                    "invoice": str(inv).strip() if inv not in (None, "") else None,
                    # the rate is a price, so a return keeps it positive
                    "rate": _num(rate) if rate not in (None, "") else None,
                    "is_return": bool(is_return)})
    return "rows (sales return)" if is_return else "rows"


def _pdf_rows(data: bytes):
    """Every table row on every page, as text. Ruled tables are read from their
    lines; a report printed without lines is read from the gaps between words."""
    import pdfplumber

    def cell(v):
        return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for settings in (None, {"vertical_strategy": "text", "horizontal_strategy": "text"}):
            rows = []
            for page in pdf.pages:
                tables = page.extract_tables(settings) if settings else page.extract_tables()
                for t in tables:
                    rows.extend([[cell(c) for c in row] for row in t if row])
            if _cross_tab_header(rows) >= 0 or _map_columns(rows):
                return rows, len(pdf.pages)
        return [], len(pdf.pages)


def read_pdf(name: str, data: bytes, negate_returns: bool = True) -> dict:
    """Every sales row in a PDF report, read as one sheet."""
    out, stats = [], {"omitted": 0}
    try:
        rows, pages = _pdf_rows(data)
    except Exception as e:
        return {"name": name, "rows": [], "omitted": 0, "sheets": [],
                "error": f"Not a PDF this can open: {type(e).__name__}"}
    how = None
    hr = _cross_tab_header(rows)
    if hr >= 0:
        how = _parse_cross_tab(rows, hr, out, stats)
    else:
        found = _map_columns(rows)
        if found:
            hr, cmap = found
            head = [_norm(c) for c in rows[hr]]
            # the header printed again at the top of every page is not a sales row
            body = [r for r in rows[hr + 1:] if [_norm(c) for c in r] != head]
            how = _parse_row_wise([rows[hr]] + body, 0, cmap, out, stats,
                                  bool(re.search(r"return", name, re.I)), negate_returns,
                                  fill_down=True)
    sheets = [{"name": f"PDF, {pages} page{'s' if pages != 1 else ''}",
               "layout": how and f"{how}, from PDF", "rows": len(out),
               "omitted": stats["omitted"]}]
    error = None if out else (
        "No sales rows could be read from this PDF. It needs a table with a header row naming "
        "customer (or party), product (or item), quantity and amount. A scanned PDF has no "
        "text to read.")
    return {"name": name, "rows": out, "omitted": stats["omitted"], "sheets": sheets,
            "error": error}


def _sheets(data: bytes) -> list[tuple[str, list[list]]]:
    """Every sheet as (title, rows of values). An .xlsx is opened with openpyxl;
    an older .xls (the binary format Yetichem's AHCPW.xls, AILGPW.xls and
    AILNPW.xls come in) with xlrd. Which one is decided by trying, because a
    file named .xls is sometimes an .xlsx underneath."""
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception:
        import xlrd                          # .xls (BIFF); raises if it is not one either
        bk = xlrd.open_workbook(file_contents=data)

        def val(c):
            if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                return None
            v = c.value
            # xlrd gives every number as a float; 1.0 must read as 1, as in .xlsx
            if c.ctype == xlrd.XL_CELL_NUMBER and float(v).is_integer():
                return int(v)
            return v

        return [(sh.name, [[val(c) for c in sh.row(r)] for r in range(sh.nrows)])
                for sh in bk.sheets()]
    try:
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)])
                for ws in wb.worksheets]
    finally:
        wb.close()


def read_book(name: str, data: bytes, negate_returns: bool = True) -> dict:
    """Every sales row in one workbook (or PDF report), with a note of how each
    sheet was read."""
    if PDF.search(name):
        return read_pdf(name, data, negate_returns)
    out, stats, sheets = [], {"omitted": 0}, []
    try:
        book = _sheets(data)
    except Exception as e:
        return {"name": name, "rows": [], "omitted": 0, "sheets": [],
                "error": f"Not a workbook this can open: {type(e).__name__}"}
    for title, rows in book:
        before, omitted_before = len(out), stats["omitted"]
        hr = _cross_tab_header(rows)
        if hr >= 0:
            how = _parse_cross_tab(rows, hr, out, stats)
        else:
            found = _map_columns(rows)
            how = (_parse_row_wise(rows, found[0], found[1], out, stats,
                                   bool(re.search(r"return", title, re.I)),
                                   negate_returns) if found else None)
        sheets.append({"name": title, "layout": how,
                       "rows": len(out) - before, "omitted": stats["omitted"] - omitted_before})
    error = None if out else (
        "No sales rows could be read. Expected either the cross-tab layout (Sn / Prodname / "
        "Unit) or a header row naming customer, product, quantity and amount.")
    return {"name": name, "rows": out, "omitted": stats["omitted"], "sheets": sheets,
            "error": error}
