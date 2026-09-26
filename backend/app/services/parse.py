"""Reading the distributors' workbooks.

Two layouts turn up. A cross-tab - products down the page, customers across,
quantities on one row and amounts on the next - and a plain row-wise sheet with
a header naming its columns. Which one a file uses is worked out from the file,
not from its name, because the names are not reliable.
"""
from __future__ import annotations

import io
import re
import zipfile

from openpyxl import load_workbook

QTY = re.compile(r"^\s*(-?[\d.,]+)\s*\+\s*(-?[\d.,]+)\s*$")
BOOK = re.compile(r"\.(xlsx|xlsm|xls)$", re.I)

WANT = {
    "customer": ["customername", "customer", "party", "partyname", "shopname"],
    "product": ["productname", "product", "item", "itemname", "particulars", "prodname"],
    "qty": ["quantity", "qty"],
    "free": ["freequantity", "freeqty", "free", "fqty"],
    "amount": ["amount", "netamount", "value", "bamount", "basicamount"],
    "invoice": ["invoiceno", "invoicenumber", "invno", "billno", "invoice"],
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
        return float(str(v if v is not None else "").replace(",", ""))
    except ValueError:
        return 0.0


def books_in(name: str, data: bytes):
    """Whatever was uploaded, reduced to workbooks: a zip is opened, a workbook
    is taken as it is, and anything else (a PDF, say) is left out."""
    if name.lower().endswith(".zip"):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                inner = info.filename
                if info.is_dir() or inner.startswith("__MACOSX/") or not BOOK.search(inner):
                    continue
                base = inner.split("/")[-1]
                if base.startswith(".") or base.startswith("_"):
                    continue
                out.append((base, z.read(info)))
        return out
    if BOOK.search(name):
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
                        "qty": q, "free": f, "amount": amt, "invoice": None, "is_return": False})
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


def _parse_row_wise(rows, hr, cmap, out, stats, is_return, negate):
    sign = -1 if (is_return and negate) else 1
    for r in range(hr + 1, len(rows)):
        row = rows[r]

        def get(k):
            return row[cmap[k]] if k in cmap and cmap[k] < len(row) else None

        cust = str(get("customer") or "").strip()
        prod = str(get("product") or "").strip()
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
        out.append({"customer": clean(cust), "product": clean(prod),
                    "qty": q * sign, "free": f * sign, "amount": _num(get("amount")) * sign,
                    "invoice": str(inv).strip() if inv not in (None, "") else None,
                    "is_return": bool(is_return)})
    return "rows (sales return)" if is_return else "rows"


def read_book(name: str, data: bytes, negate_returns: bool = True) -> dict:
    """Every sales row in one workbook, with a note of how each sheet was read."""
    out, stats, sheets = [], {"omitted": 0}, []
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as e:
        return {"name": name, "rows": [], "omitted": 0, "sheets": [],
                "error": f"Not a workbook this can open: {type(e).__name__}"}
    try:
        for sheet in wb.worksheets:
            rows = [list(r) for r in sheet.iter_rows(values_only=True)]
            before, omitted_before = len(out), stats["omitted"]
            hr = _cross_tab_header(rows)
            if hr >= 0:
                how = _parse_cross_tab(rows, hr, out, stats)
            else:
                found = _map_columns(rows)
                how = (_parse_row_wise(rows, found[0], found[1], out, stats,
                                       bool(re.search(r"return", sheet.title, re.I)),
                                       negate_returns) if found else None)
            sheets.append({"name": sheet.title, "layout": how,
                           "rows": len(out) - before, "omitted": stats["omitted"] - omitted_before})
    finally:
        wb.close()
    error = None if out else (
        "No sales rows could be read. Expected either the cross-tab layout (Sn / Prodname / "
        "Unit) or a header row naming customer, product, quantity and amount.")
    return {"name": name, "rows": out, "omitted": stats["omitted"], "sheets": sheets,
            "error": error}
