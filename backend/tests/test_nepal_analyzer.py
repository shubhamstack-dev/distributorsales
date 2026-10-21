"""Nepal Analyzer (Reports menu): the old Reports/NewNepal_Analyser.aspx, with
its mistakes put right (see app/reports/nepal_analyzer.py).

* September 2026's MAPPING_MASTER / _MID and employees are rebuilt from the old
  file (tests/data) and the report is run: every sheet and heading is the old
  file's, and the sales, distributor and employee figures agree with it.
* A small budget, worked out by hand, checks the budget sheets and each fix.

Set NEPAL_TEST_MYSQL=mysql+pymysql://user:pw@host/db to run them on MySQL as
well (its tables are dropped and made again).
"""
import io
import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.harness import client, ok, sign_in                     # noqa: F401  (app set up)
from app.database import Base
from app import models_master as M
from app.reports import nepal_analyzer as N

FILE = Path(__file__).parent / "data" / "NepalAnalyzerReports_September2026.xlsx"
URLS = ["sqlite://"] + ([os.environ["NEPAL_TEST_MYSQL"]] if os.environ.get("NEPAL_TEST_MYSQL") else [])


def _old():
    wb = load_workbook(FILE, read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
        head = list(rows[0])
        while head and head[-1] is None:            # the old file styled a few empty columns too
            head.pop()
        out[ws.title] = (head, [dict(zip(head, r)) for r in rows[1:]])
    return out


OLD = _old()


def _session(url):
    eng = create_engine(url)
    if url.startswith("mysql"):
        with eng.begin() as c:
            c.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for t in reversed(Base.metadata.sorted_tables):
                c.execute(text(f"DROP TABLE IF EXISTS `{t.name}`"))
            c.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _close(db):
    db.rollback()
    db.close()
    db.get_bind().dispose()            # nothing left holding the tables (MySQL drops them next)


def _r2(x):
    return float(Decimal(repr(x)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _sheet(sheets, name) -> N.Sheet:
    return next(s for s in sheets if s.name == name)


def _rows(sh: N.Sheet):
    return [dict(zip(sh.columns, r), _kind=k) for r, k in zip(sh.rows, sh.kinds)]


# ------------------------------------------------- September, from the old file
def _rate(q, ret, inr_rate, inr, npr):
    """The NPR rate behind a SALES row (the file gives it only in INR, rounded)."""
    n = q + ret
    if n:
        for k in (2, 3, 4, 5, 6):
            r = round(npr / n, k)
            if _r2(r / 1.6) == inr_rate and _r2(n * r) == npr and _r2(n * r / 1.6) == inr:
                return r
        return round(npr / n, 2)
    return round(inr_rate * 1.6, 2)


def _mapping(name):
    out, brands = [], {}
    for i, s in enumerate((r for r in OLD[name][1] if not str(r["DISTRIBUTOR ID"]).startswith("Total")), 1):
        out.append(dict(
            ID=i, DIST_ID=int(s["DISTRIBUTOR ID"]), DIST_NAME=s["DISTRIBUTOR"], CUSTOMER_ID=int(s["CUSTOMER ID"]),
            CUSTOMER_MASTER_NAME=s["CUSTOMER NAME"], CUSTOMER_NAME=s["CUSTOMER NAME"],
            PRODUCT_GROUP_ID=int(s["DIVISION ID"]), PRODUCT_GROUP_NAME=s["DIVISION"],
            PRODUCT_BRAND_ID=brands.setdefault(s["BRAND"], len(brands) + 1), PRODUCT_BRAND_NAME=s["BRAND"],
            PRODUCT_BRAND_CATEGORY=s["PRODUCT CATEGORY"], PRODUCT_ID=int(s["SKU ID"]),
            PRODUCT_MASTER_NAME=s["SKU"], PRODUCT_NAME=s["SKU"], HQ_ID=int(s["HQ ID"]), HQ_NAME=s["HQ NAME"],
            SALES_QTY=s["SALES QTY"], FREE_QUANTITY=s["FREE QTY"], RETURN_QUANTITY=s["RETURN QTY"],
            RATE=_rate(s["SALES QTY"], s["RETURN QTY"], s["RATE"], s["SALES VALUE(INR)"], s["SALES VALUE(NPR)"]),
            MONTH=s["MONTH"], YEAR=int(s["YEAR"])))
    return out


def _masters(db, hq, pg):
    c = M.Country(code="NP", name="Nepal", currency_code="NPR")
    db.add(c)
    db.flush()
    z = M.Zone(code="Z1", name="ZONE1", country_id=c.id, legacy_id=1)
    db.add(z)
    db.flush()
    for i, n in hq.items():
        db.add(M.Headquarter(code=f"H{i}", name=n, zone_id=z.id, legacy_id=i))
    for i, n in pg.items():
        db.add(M.ProductGroup(code=f"P{i}", name=n, legacy_id=i))
    db.add(M.Designation(code="ABM", name="ABM", level=2, legacy_id=2))
    db.add(M.Designation(code="TBM", name="TBM", level=1, legacy_id=3))
    db.flush()


def _seed_september(db):
    sales, mid = _mapping("SALES"), _mapping("SALES MID")
    hq = {r["HQ_ID"]: r["HQ_NAME"] for r in sales + mid}
    pg = {r["PRODUCT_GROUP_ID"]: r["PRODUCT_GROUP_NAME"] for r in sales + mid}
    _masters(db, hq, pg)
    db.execute(M.SalesMapping.__table__.insert(), sales)
    db.execute(M.MidSalesMapping.__table__.insert(), [{**r, "MID": "Y"} for r in mid])
    hq_id, pg_id = {n: i for i, n in hq.items()}, {n: i for i, n in pg.items()}
    cover = {}
    for r in OLD["EMPLOYEE SALES"][1]:
        if not str(r["DISTRIBUTOR ID"]).startswith("Total"):
            for n in (r["EMPLOYEE NAME"] or "").split(","):
                if n.strip():
                    cover.setdefault(n, (set(), set()))
                    cover[n][0].add(r["DIVISION"])
                    cover[n][1].add(r["HQ NAME"])
    for k, (n, (ds, hs)) in enumerate(sorted(cover.items()), start=1):
        ft, _, lt = n.partition(" ")
        db.add(M.EmployeeMaster(id=k, employee_ft_nm=ft, employee_lt_nm=lt, active=1, designation_id=3))
        db.flush()
        db.execute(M.EmployeePgAssignment.__table__.insert(), [
            dict(EMPLOYEE_ID=k, PRODUCT_ID=0, PRODUCT_BRAND_ID=0, PRODUCT_GROUP_ID=pg_id[d]) for d in ds])
        db.execute(M.EmployeeTerrAssignment.__table__.insert(), [
            dict(EMPLOYEE_ID=k, HQ_ID=hq_id[h], TERRITORY_ID=0) for h in hs])
    db.commit()


@pytest.fixture(scope="module", params=URLS, ids=lambda u: u.split(":")[0])
def september(request):
    db = _session(request.param)
    _seed_september(db)
    sheets = N.build(db, "September", 2026)
    _close(db)
    return sheets


def test_every_sheet_and_heading_as_the_old_file(september):
    assert [s.name for s in september] == N.SHEETS == list(OLD)
    for s in september:
        assert s.columns == OLD[s.name][0], s.name


def _key(r):
    return (int(r["DISTRIBUTOR ID"]), int(r["CUSTOMER ID"]), int(r["SKU ID"]), int(r["HQ ID"]))


@pytest.mark.parametrize("name", ["SALES", "SALES MID", "EMPLOYEE SALES"])
def test_sales_figures_as_the_old_file(september, name):
    new = {}
    for r in _rows(_sheet(september, name)):
        if r["_kind"] is None:
            new.setdefault(_key(r), []).append(r)
    old = [r for r in OLD[name][1] if not str(r["DISTRIBUTOR ID"]).startswith("Total")]
    assert sum(len(v) for v in new.values()) == len(old)
    for o in old:
        cands = new[_key(o)]
        n = min(cands, key=lambda r: abs(r["RATE"] - o["RATE"]))
        for c in ("SALES QTY", "FREE QTY", "RETURN QTY", "TOTAL QTY", "SALES VALUE(NPR)"):
            assert n[c] == pytest.approx(o[c], abs=0.011), (o, c)
        assert n["SALES VALUE(INR)"] == pytest.approx(o["SALES VALUE(INR)"], abs=0.021)
        if name == "EMPLOYEE SALES":       # the same people, without the stray double spaces
            assert n["EMPLOYEE NAME"] == " ".join(o["EMPLOYEE NAME"].split()).replace(", ", ",")
            assert n["TEAM"] == o["TEAM"]


@pytest.mark.parametrize("name", ["SALES", "SALES MID", "EMPLOYEE SALES"])
def test_sales_total_is_the_real_total(september, name):
    """The old Total added the rounded INR rows (63987522.23); the real one is
    the NPR total / 1.6 (102380034.97 / 1.6 = 63987521.86)."""
    rows = _rows(_sheet(september, name))
    tot = rows[-1]
    old_tot = OLD[name][1][-1]
    assert tot["_kind"] == "total" and tot["SALES VALUE(NPR)"] == old_tot["SALES VALUE(NPR)"]
    assert tot["SALES VALUE(INR)"] == _r2(old_tot["SALES VALUE(NPR)"] / 1.6)


def test_sales_in_sku_order(september):
    """MAPPING_MASTER's PRODUCT_ID is a number here: SKU 40 before SKU 155."""
    rows = [r for r in _rows(_sheet(september, "SALES")) if r["_kind"] is None]
    one = [r["SKU ID"] for r in rows if (r["DISTRIBUTOR ID"], r["CUSTOMER ID"], r["HQ NAME"]) ==
           (18671704, 12, "BIRATNAGAR") and r["DIVISION"] == "METABOLICS-NEW"]
    assert one == sorted(one) and len(one) > 3


@pytest.mark.parametrize("name", ["DISTRIBUTOR LEVEL", "DISTRIBUTOR LEVEL EXPIRY ADJUST"])
def test_distributor_level_as_the_old_file(september, name):
    new = _rows(_sheet(september, name))
    assert [[r[c] for c in OLD[name][0]] for r in new] == [[r[c] for c in OLD[name][0]] for r in OLD[name][1]]


def test_nepal_level_month_sale(september):
    assert _rows(_sheet(september, "NEPAL LEVEL"))[8]["MONTH SALE"] == 639.88


def test_sales_adjustment_agrees_with_sales(september):
    """The old SALES ADJUSTMENT rounded each rate first, so its total was not
    SALES' total; now it is."""
    adj = _rows(_sheet(september, "SALES ADJUSTMENT"))
    assert adj[-1]["AMOUNT"] == _rows(_sheet(september, "SALES"))[-1]["SALES VALUE(INR)"]
    ids = [r["CUSTOMER ID"] for r in adj[:-1]]
    assert ids == sorted(ids)


# ------------------------------------------------------- the budget, by hand
def _budget_row(n, emp, year, pg, hq, brand, pid, cat="P1", **vals):
    row = {"S_NO": n, "EMPLOYEE_ID": emp, "HQ_ID": 1, "HQ_NAME": hq, "PRODUCT_GROUP": pg,
           "PRODUCT_GROUP_ID": 1, "PRODUCT_BRAND": brand, "PRODUCT_BRAND_ID": 1, "PRODUCT_ID": pid,
           "PRODUCT_NAME": f"{brand} {pid}", "TARGET_YEAR": year, "PRODUCT_BRAND_CATEGORY": cat}
    for c, _ in M.BUDGET_COLUMNS:
        if c not in row and c != "ID":
            row[c] = None
    row.update(vals)
    return row


@pytest.fixture(params=URLS, ids=lambda u: u.split(":")[0])
def budget(request):
    db = _session(request.param)
    _masters(db, {1: "BIRATNAGAR"}, {1: "GASTRO"})
    db.add(M.EmployeeMaster(id=10, employee_ft_nm="Asha", employee_lt_nm="Rai", designation_id=2,
                            team="GASTRO", active=1, start_date=date(2019, 1, 1)))
    db.add(M.EmployeeMaster(id=20, employee_ft_nm="Bina", employee_lt_nm="Shah", designation_id=3,
                            team="GASTRO", active=1, start_date=date(2021, 9, 15), employee_code="500041"))
    db.add(M.HeadCount(division="GASTRO", hq="BIRATNAGAR", count=2))
    db.add(M.HeadCount(division="WH", hq="BUTWAL", count=1))
    rows = [
        # GASTRO, BIRATNAGAR: targets 1, 2, 3 lakh; actuals 1.6, 3.2, 4.8 lakh NPR = 1, 2, 3 lakh INR
        _budget_row(1, 10, 2026, "GASTRO", "BIRATNAGAR", "CREMAFFIN", 51, JANUARY=100000, FEBRUARY=200000,
                    MARCH=300000, JANUARY_ACTUAL=1.6, FEBRUARY_ACTUAL=3.2, MARCH_ACTUAL=4.8,
                    MARCH_MID_ACTUAL=0.8, JUNE_RETURN=-50000, MARCH_RETURN=-20000, JANUARY_RETURN=-10000,
                    MARCH_EXPIRY_ADJUSTED=0.32),
        _budget_row(2, 10, 2025, "GASTRO", "BIRATNAGAR", "CREMAFFIN", 51, JANUARY_ACTUAL=1.6,
                    FEBRUARY_ACTUAL=1.6, MARCH_ACTUAL=3.2),
        # FEBRUARY left empty: the old YTD dropped the whole row; it counts as 0 now
        _budget_row(3, 10, 2026, "GASTRO", "BIRATNAGAR", "CREMAFFIN PLUS", 52, JANUARY=100000,
                    MARCH=100000, MARCH_ACTUAL=1.6),
        # a brand with no target ahead of one with a target (its sums ran on into the next Total)
        _budget_row(4, 10, 2026, "GASTRO", "BIRATNAGAR", "ANTOXIPAN", 53, MARCH=0, MARCH_ACTUAL=16),
        # WH, BUTWAL: a second division
        _budget_row(5, 10, 2026, "WH", "BUTWAL", "DUPHASTON", 60, MARCH=200000, MARCH_ACTUAL=3.2,
                    JANUARY_RETURN=-30000, JUNE_RETURN=-40000),
        # the TBM
        _budget_row(6, 20, 2026, "GASTRO", "BIRATNAGAR", "CREMAFFIN", 51, cat="P2", JANUARY=50000,
                    FEBRUARY=50000, MARCH=100000, MARCH_ACTUAL=1.6),
    ]
    db.execute(M.Budget.__table__.insert(), rows)
    db.execute(M.Adjustment.__table__.insert(), [
        dict(ID=1, DIST_NAME="YETICHEM", MONTH="November", YEAR=2026, EXPIRY_TOTAL_AMOUNT=160000),
        dict(ID=2, DIST_NAME="YETICHEM", MONTH="October", YEAR=2026, EXPIRY_TOTAL_AMOUNT=320000)])
    db.execute(M.SalesMapping.__table__.insert(), [
        dict(ID=1, DIST_ID=1, DIST_NAME="YETICHEM", CUSTOMER_ID=5, CUSTOMER_MASTER_NAME="TOTAL HEALTH PHARMA",
             PRODUCT_GROUP_ID=1, PRODUCT_GROUP_NAME="GASTRO", PRODUCT_ID=51, PRODUCT_BRAND_NAME="CREMAFFIN",
             HQ_ID=1, HQ_NAME="BIRATNAGAR", SALES_QTY=10, FREE_QUANTITY=0, RETURN_QUANTITY=None, RATE=160,
             MONTH="March", YEAR=2026)])
    db.commit()
    sheets = N.build(db, "March", 2026)
    nov = N.build(db, "November", 2026)
    _close(db)
    return sheets, nov


def _by(rows, **kv):
    return next(r for r in rows if all(r.get(k) == v for k, v in kv.items()))


def test_hq_level_by_hand(budget):
    rows = _rows(_sheet(budget[0], "HQ LEVEL"))
    g = _by(rows, DIVISION="GASTRO", HQ="BIRATNAGAR")
    # YTD target 1+2+3 + 1+0+1 lakh = 8; actual 1+2+3 + 1 + 10 = 17 INR lakh (ANTOXIPAN's 16 NPR = 10)
    assert (g["HEAD COUNT"], g["YTD TARGET(INR)"], g["YTD ACTUAL SALE(INR)"]) == (2, 8, 17)
    assert g["YTD % ACH"] == 212.5 and g["YTD LYR"] == 4 and g["YTD % GROWTH"] == 325
    assert g["YTD PCPM"] == 8.5
    assert (g["March TARGET(INR)"], g["March ACTUAL SALE(INR)"], g["March MID ACTUAL SALE(INR)"]) == (4, 14, 0.5)
    assert g["March LYR"] == 2 and g["March % GROWTH"] == 600 and g["March PCPM"] == 7
    assert [(r["DIVISION"], r["_kind"]) for r in rows] == [
        ("GASTRO", None), ("GASTRO Total", "total"), ("WH", None), ("WH Total", "total"), ("All Total", "all")]
    w = _by(rows, DIVISION="WH")
    assert w["YTD % GROWTH"] is None and w["YTD LYR"] == 0          # nothing last year: empty, not 0
    tot = rows[-1]
    assert tot["YTD TARGET(INR)"] == 10 and tot["HEAD COUNT"] == 3 and tot["YTD ACTUAL SALE(INR)"] == 19


def test_expiry_taken_off_in_inr(budget):
    g = _by(_rows(_sheet(budget[0], "HQ LEVEL EXPIRY ADJUST")), DIVISION="GASTRO", HQ="BIRATNAGAR")
    assert g["March EXPIRY ADJUSTED(INR)"] == 0.2                   # 0.32 lakh NPR
    assert g["March NET SALE(INR)"] == 13.8                         # 14 - 0.2 (the old sheet took 0.32)
    assert g["March % ACH"] == 345 and g["YTD NET SALE(INR)"] == 16.8


def test_brand_totals_hold_their_own_group_and_sit_under_it(budget):
    rows = _rows(_sheet(budget[0], "BRAND LEVEL"))
    assert [r["BRAND"] for r in rows] == ["ANTOXIPAN", "ANTOXIPAN Total", "CREMAFFIN", "CREMAFFIN Total",
                                         "CREMAFFIN PLUS", "CREMAFFIN PLUS Total", "DUPHASTON",
                                         "DUPHASTON Total", "All Total"]
    a = _by(rows, BRAND="ANTOXIPAN Total")
    assert a["YTD TARGET(INR)"] == 0 and a["YTD ACTUAL SALE(INR)"] == 10 and a["YTD % ACH"] is None
    c = _by(rows, BRAND="CREMAFFIN Total")                          # only CREMAFFIN: 6 target, 6 + 0 actual
    assert (c["YTD TARGET(INR)"], c["YTD ACTUAL SALE(INR)"]) == (6, 6)
    p = _by(rows, BRAND="CREMAFFIN PLUS")                           # the empty February counts as 0
    assert (p["YTD TARGET(INR)"], p["YTD ACTUAL SALE(INR)"]) == (2, 1)


def test_all_hq_returns(budget):
    rows = _rows(_sheet(budget[0], "ALL HQ LEVEL"))
    g, w = _by(rows, DIVISION="GASTRO Total"), _by(rows, DIVISION="WH Total")
    # returns are INR already: -10000 + -20000 = -0.3 lakh (the old sheet: /160000, and the month / head count)
    assert g["YTD RETURN"] == -0.3 and g["JANUARY RETURN"] == -0.1 and g["MARCH RETURN"] == -0.2
    assert g["JUNE RETURN"] == -0.5                                 # June's own (the old sheet added January's)
    assert w["YTD RETURN"] == -0.3                                  # WH's own (the old sheet carried GASTRO's)
    assert rows[-1]["YTD RETURN"] == -0.6 and rows[-1]["JUNE RETURN"] == -0.9


def test_the_same_all_total_on_every_sheet(budget):
    s = budget[0]
    nepal = _rows(_sheet(s, "NEPAL LEVEL"))[2]["YTD TARGET"]
    alls = [_rows(_sheet(s, n))[-1]["YTD TARGET(INR)"] for n in
            ("HQ LEVEL", "BRAND LEVEL", "BRAND LEVEL EXPIRY ADJUST", "HQ and BRAND LEVEL", "ALL HQ LEVEL",
             "ALL BRAND LEVEL")]
    assert set(alls) == {nepal} == {10}


def test_hq_and_brand_totals(budget):
    rows = _rows(_sheet(budget[0], "HQ and BRAND LEVEL"))
    assert [(r["DIVISION"], r["HQ"]) for r in rows if r["_kind"]] == [
        ("GASTRO", "BIRATNAGAR - GASTRO Total"), ("GASTRO Total", None), ("WH", "BUTWAL - WH Total"),
        ("WH Total", None), ("All Total", None)]


def test_employee_performance(budget):
    rows = _rows(_sheet(budget[0], "EMPLOYEE SALES PERFORMANCE"))
    t, a = rows[0], rows[1]
    assert (t["EMPLOYEE NAME"], t["DESIGNATION"], t["HQ"], t["JOINING DATE"], t["EMPLOYEE CODE"]) == \
        ("Bina Shah", "TBM", "BIRATNAGAR", "15/09/2021", "500041")
    assert t["YTD TARGET P2"] == 2 and t["March TOTAL ACTUAL SALE"] == 1 and t["YTD P1 % ACH"] is None
    assert (a["EMPLOYEE NAME"], a["DESIGNATION"], a["HQ"]) == ("Asha Rai", "ABM", "Kathmandu")
    assert [r["DIVISION"] for r in rows] == ["GASTRO", "GASTRO", "WH", "All Total(Rahul Dharwad)"]
    assert rows[-1]["YTD TARGET TOTAL"] == 10


def test_nepal_level(budget):
    rows = _rows(_sheet(budget[1], "NEPAL LEVEL EXPIRY ADJUST"))
    nov = rows[10]
    assert nov["MONTH"] == "NOVEMBER" and nov["EXPIRY ADJUSTED"] == 1
    assert nov["YTD EXPIRY"] == 3                                    # October's 2 and November's 1
    assert nov["MONTH % ACH"] is None                                # no target: empty, not NaN
    mar = _rows(_sheet(budget[0], "NEPAL LEVEL"))[2]
    # 10 x 160 NPR with an empty return quantity: counted (the old query dropped it)
    assert mar["MONTH SALE"] == 0.01 and mar["MONTH TARGET"] == 6


def test_only_total_rows_are_coloured(budget):
    sales = _rows(_sheet(budget[0], "SALES"))
    assert sales[0]["CUSTOMER NAME"] == "TOTAL HEALTH PHARMA" and sales[0]["_kind"] is None
    wb = load_workbook(io.BytesIO(N.workbook(budget[0])))
    assert wb["SALES"]["D2"].fill.fill_type is None
    assert wb["SALES"]["A3"].fill.fgColor.rgb == "FF90EE90"


# ---------------------------------------------------------------- the API
def test_download_from_the_api():
    h = {"Authorization": "Bearer " + sign_in()}
    assert client.get("/api/reports/nepal-analyzer?month=&year=2026", headers=h).status_code == 400
    assert client.get("/api/reports/nepal-analyzer?month=September&year=x", headers=h).status_code == 400
    assert client.get("/api/reports/nepal-analyzer?month=September&year=2026").status_code == 401
    r = client.get("/api/reports/nepal-analyzer?month=september&year=2026", headers=h)
    assert r.status_code == 200, r.text
    assert 'filename="NepalAnalyzerReports_September2026.xlsx"' in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == N.SHEETS
    ws = wb["HQ LEVEL"]
    assert ws["A1"].value == "DIVISION" and ws["A1"].font.name == "Georgia" and ws["A1"].font.b
    assert ws["A1"].font.sz == 9 and ws["A1"].fill.fgColor.rgb == "FF89CFF0"
    assert ws["A1"].border.left.style == "thin"
    assert ws["A2"].value == "All Total" and ws["A2"].fill.fgColor.rgb == "FFF4C2C2"


def test_expiry_and_adjustment_upload():
    """Book1.xlsx's two new sheets go in through Upload master data."""
    h = {"Authorization": "Bearer " + sign_in()}
    wb = Workbook()
    ws = wb.active
    ws.title = "MAPPING_MASTER_EXPIRY"
    ws.append([c for c, _ in M.EXPIRY_COLUMNS])
    ws.append([9001, 12664157, "INDERAL TABS 10MG", 189, 5, 29.04, 9, "January", 2022, 9, 18, "GUNJESHWARI",
               "ACTIVE", 76, "NULL", "NULL", "NULL", "NULL", "NULL", "NMC", "NMC", "VACCINE-NEURO",
               date(2022, 1, 1), 18.15, "INA9002", "31/12/1899", 1721.5444, 1721.5444, 0, "NARAYANGHAT",
               "NARAYANGHAT", "INDERAL", 1, "NULL", "NULL", 147, 0, 0, "INDERAL TABS 10MG", "X-OTHERS", "Y"])
    ws2 = wb.create_sheet("ADJUSTMENT")
    ws2.append([c for c, _ in M.ADJUSTMENT_COLUMNS])
    ws2.append([9001, 12664157, "INDERAL TABS 10MG", 189, 5, 29.04, 9, "March", 2022, 9, 18, "GUNJESHWARI",
                "ACTIVE", -76, "NMC", "NMC", "VACCINE-NEURO", "NARAYANGHAT", "NARAYANGHAT", "INDERAL", "AH21/43",
                "NULL", "NULL", 147, 0, 0, "INDERAL TABS 10MG", "X-OTHERS", "2022.02.21", 18.15, 907, "NULL",
                -1721.5444, 0, "Y", 76, 29.04, 1721.5444, 1721.5444, 0, "January"])
    buf = io.BytesIO()
    wb.save(buf)
    files = [("files", ("Book1.xlsx", buf.getvalue(), "application/octet-stream"))]
    for dry, added in ((True, 1), (False, 1), (False, 0)):
        r = ok(client.post("/api/masters/upload", headers=h, data={"dry_run": str(dry).lower()}, files=files))
        got = {t["master"]: (t["added"], t["skipped"]) for t in r["tables"]}
        assert got == {"Expiry sales": (added, 0), "Adjustment": (added, 0)}, r
    rows = ok(client.get("/api/masters/adjustment", headers=h))
    assert any(x.get("id") == 9001 for x in rows["rows"])
