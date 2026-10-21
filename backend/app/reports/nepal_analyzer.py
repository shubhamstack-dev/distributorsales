"""The Nepal Analyzer report: one workbook of 18 sheets for a month and year,
laid out as the old page Reports/NewNepal_Analyser.aspx made it
(NepalAnalyzerReports_<Month><Year>.xlsx): the same sheets, the same columns,
Georgia 9, a baby-blue heading, Total rows light green and All Total pink.

What it works out is the old page's, with its mistakes put right:

* **Totals add the real figures, not the rounded ones.** The old page added
  up each row's rounded lakhs, so the same All Total came out as 5041.98 on
  one sheet, 5041.95 on another and 5042.00 on a third. Every Total here is
  worked out from the unrounded sums, the same way as its rows.
* **A Total holds its own group only.** The old page set its running sums
  back to 0 only after it wrote a Total, so a group with no target ran on into
  the next group's Total; ALL HQ LEVEL never set YTD RETURN back at all, so
  every division's Total carried the ones before it; JUNE RETURN added the
  January returns instead of June's.
* **A Total sits under its own rows.** The old page sorted Totals in by their
  name, so "CREMAFFIN Total" came after the CREMAFFIN PLUS rows.
* **Returns are in INR lakh.** BUDGET_MASTER keeps <M>_RETURN in INR already;
  the old queries took 1.6 off it a second time (/160000), and ALL HQ LEVEL
  also divided each month's return by the head count.
* **Expiry is taken off in INR.** The EXPIRY ADJUST sheets took the expiry off
  the NET SALE before turning it into INR; NEPAL LEVEL's November YTD expiry
  left November out (the query said NOVEMVER).
* **One empty month no longer empties the year.** In the old queries a row
  with any month left empty dropped out of the whole YTD (JANUARY+FEBRUARY+…
  is NULL); here an empty month counts as 0. The same for a sales line with an
  empty return quantity.
* **Sales are worked out in full precision.** The old queries turned
  quantities and rates into single-precision FLOAT (CAST … AS FLOAT), and
  SALES ADJUSTMENT rounded each rate to 2 places first, so its total did not
  agree with SALES.
* **No 0 where there is nothing to divide by.** A % ACH with no target, a %
  GROWTH with no last year or a PCPM with no head count is left empty, on the
  rows as on the Totals (the old Totals said 0, NEPAL LEVEL said NaN or
  -Infinity).
* **Only a real Total row is coloured.** The old page coloured any row with
  "total" anywhere in it, a customer's name included.

And it is quicker: the budget is read once for all eight budget sheets (the
old page scanned BUDGET_MASTER nine times, across every year), each sales
query runs once (the old page ran SALES and EXPIRY twice) and only for the
year asked, and the employees of every HQ come from one query (the old page
asked once per sales row, twice over).
"""
from __future__ import annotations

import io
import re
from functools import lru_cache
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import xlsxwriter
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import models_master as X

MONTHS = [m.title() for m in X.MONTHS]           # January … December
UP = list(X.MONTHS)                              # JANUARY … DECEMBER
ABM, TBM = 2, 3                                  # DESIGNATION Master IDs
LAKH = 100000.0
INR = 1.6                                        # NPR per INR, as the old report

SHEETS = ["NEPAL LEVEL", "NEPAL LEVEL EXPIRY ADJUST", "DISTRIBUTOR LEVEL",
          "DISTRIBUTOR LEVEL EXPIRY ADJUST", "HQ LEVEL", "HQ LEVEL EXPIRY ADJUST", "BRAND LEVEL",
          "BRAND LEVEL EXPIRY ADJUST", "HQ and BRAND LEVEL", "ALL HQ LEVEL", "ALL BRAND LEVEL",
          "EMPLOYEE SALES PERFORMANCE", "SALES", "SALES MID", "EMPLOYEE SALES", "EXPIRY SALES",
          "EMPLOYEE EXPIRY SALES", "SALES ADJUSTMENT"]


def file_name(month: str, year: int) -> str:
    return f"NepalAnalyzerReports_{month}{year}.xlsx"


# ===================================================================== values
def r2(x):
    """Rounded to 2 places, a half away from zero; None stays None."""
    if x is None:
        return None
    v = float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return 0.0 if v == 0 else v


def pct(a, b):
    return None if not b else a / b * 100


def growth(a, last):
    return None if not last else (a / last - 1) * 100


def per(a, n):
    return None if not n else a / n


def ci(s) -> str:
    """How MySQL compares and sorts these names: case-blind, ends trimmed."""
    return (s or "").strip().casefold()


@dataclass
class Sheet:
    name: str
    columns: list[str]
    rows: list[list] = field(default_factory=list)
    kinds: list[str | None] = field(default_factory=list)       # None | "total" | "all"

    def add(self, row: dict, kind: str | None = None):
        self.rows.append([row.get(c) for c in self.columns])
        self.kinds.append(kind)


# ===================================================================== budget
class Sums:
    """A group's budget figures, by month: the target year's target, actual,
    mid-month actual, return and expiry adjusted, last year's actual. Raw
    (NPR, lakh NPR, INR as BUDGET_MASTER keeps them); rounded only when shown."""
    __slots__ = ("tgt", "act", "mid", "ret", "exp", "ly", "hc")

    def __init__(self):
        self.tgt, self.act, self.mid, self.ret, self.exp, self.ly = ([0.0] * 12 for _ in range(6))
        self.hc = None

    def add(self, o: "Sums"):
        for a in ("tgt", "act", "mid", "ret", "exp", "ly"):
            x, y = getattr(self, a), getattr(o, a)
            for i in range(12):
                x[i] += y[i]
        if o.hc is not None:
            self.hc = (self.hc or 0) + o.hc


@dataclass
class Figures:
    """What the sheets show for one group (or Total), for month k (1–12)."""
    s: Sums
    k: int

    def ytd(self, a, div):
        return sum(getattr(self.s, a)[:self.k]) / div

    def mon(self, a, div, m=None):
        return getattr(self.s, a)[(self.k if m is None else m) - 1] / div

    @property
    def y_tgt(self): return self.ytd("tgt", LAKH)
    @property
    def y_act(self): return self.ytd("act", INR)
    @property
    def y_ly(self): return self.ytd("ly", INR)
    @property
    def y_exp(self): return self.ytd("exp", INR)
    @property
    def y_ret(self): return self.ytd("ret", LAKH)
    @property
    def m_tgt(self): return self.mon("tgt", LAKH)
    @property
    def m_act(self): return self.mon("act", INR)
    @property
    def m_mid(self): return self.mon("mid", INR)
    @property
    def m_ly(self): return self.mon("ly", INR)
    @property
    def m_exp(self): return self.mon("exp", INR)


def _n(v) -> float:
    return float(v) if v is not None else 0.0


def read_budget(db: Session, year: int) -> list[dict]:
    """The budget rows the eight budget sheets need, in two queries: the ABMs'
    rows of the year and the year before, as they are; the TBMs' of the year,
    already added up by HQ, division, employee and category (all their sheet
    shows), which saves sending thousands of rows across."""
    from sqlalchemy import func
    B, E, D = X.Budget, X.EmployeeMaster, X.Designation
    month_cols = [getattr(B, X.attr_of(m + suffix)) for m in UP
                  for suffix in ("", "_ACTUAL", "_MID_ACTUAL", "_RETURN", "_EXPIRY_ADJUSTED")]
    who = [B.product_group, B.hq_name, B.employee_id, D.name.label("designation_name"), E.employee_code,
           E.employee_ft_nm, E.employee_lt_nm, E.start_date]
    names = ["pg", "hq", "emp", "desig_name", "code", "ft", "lt", "start"]
    base = select().join(E, E.id == B.employee_id).join(D, D.legacy_id == E.designation_id)
    abm = base.add_columns(B.target_year, B.product_brand, B.product_id, B.product_name,
                           B.product_brand_category, *who, *month_cols) \
        .select_from(B).where(B.target_year.in_([year, year - 1]), D.legacy_id == ABM)
    tbm = base.add_columns(B.target_year, B.product_brand_category, *who, *[func.sum(c) for c in month_cols]) \
        .select_from(B).where(B.target_year == year, D.legacy_id == TBM) \
        .group_by(B.target_year, B.product_brand_category, *who)
    out = []
    for desig, q, head in ((ABM, abm, ["year", "brand", "pid", "product", "cat"] + names),
                           (TBM, tbm, ["year", "cat"] + names)):
        for r in db.execute(q):
            d = dict(zip(head, r[:len(head)]), desig=desig)
            vals = r[len(head):]
            s = Sums()
            cur = d["year"] == year
            for i in range(12):
                t, a, mid, ret, ex = (_n(v) for v in vals[i * 5:i * 5 + 5])
                if cur:
                    s.tgt[i], s.act[i], s.mid[i], s.ret[i], s.exp[i] = t, a, mid, ret, ex
                else:
                    s.ly[i] = a
            d["sums"] = s
            out.append(d)
    return out


def head_counts(db: Session) -> dict:
    return {(ci(d), ci(h)): c for d, h, c in db.execute(
        select(X.HeadCount.division, X.HeadCount.hq, X.HeadCount.count))}


class Groups:
    """Budget rows summed by a key; the first spelling of each name is shown."""

    def __init__(self, rows, key, label):
        self.sums: dict = {}
        self.label: dict = {}
        for r in rows:
            k = key(r)
            if k not in self.sums:
                self.sums[k] = Sums()
                self.label[k] = label(r)
            self.sums[k].add(r["sums"])

    def keys(self):
        return sorted(self.sums)


def total_of(sums_list) -> Sums:
    t = Sums()
    for s in sums_list:
        t.add(s)
    return t


def _hq_cols(mon, expiry):
    c = ["DIVISION", "HQ", "HEAD COUNT", "YTD TARGET(INR)", "YTD ACTUAL SALE(INR)"]
    if expiry:
        c += ["YTD EXPIRY ADJUSTED(INR)", "YTD NET SALE(INR)"]
    c += ["YTD % ACH", "YTD % GROWTH", "YTD LYR", "YTD PCPM", f"{mon} TARGET(INR)",
          f"{mon} ACTUAL SALE(INR)"]
    if expiry:
        c += [f"{mon} EXPIRY ADJUSTED(INR)", f"{mon} NET SALE(INR)"]
    return c + [f"{mon} MID ACTUAL SALE(INR)", f"{mon} % ACH", f"{mon} % GROWTH", f"{mon} LYR",
                f"{mon} PCPM"]


def _hq_row(f: Figures, mon, expiry, first: dict):
    ynet, mnet = (f.y_act - f.y_exp, f.m_act - f.m_exp) if expiry else (f.y_act, f.m_act)
    hc = f.s.hc
    return {**first, "HEAD COUNT": hc, "YTD TARGET(INR)": r2(f.y_tgt), "YTD ACTUAL SALE(INR)": r2(f.y_act),
            "YTD EXPIRY ADJUSTED(INR)": r2(f.y_exp), "YTD NET SALE(INR)": r2(ynet),
            "YTD % ACH": r2(pct(ynet, f.y_tgt)), "YTD % GROWTH": r2(growth(f.y_act, f.y_ly)),
            "YTD LYR": r2(f.y_ly), "YTD PCPM": r2(per(f.y_act, hc)),
            f"{mon} TARGET(INR)": r2(f.m_tgt), f"{mon} ACTUAL SALE(INR)": r2(f.m_act),
            f"{mon} EXPIRY ADJUSTED(INR)": r2(f.m_exp), f"{mon} NET SALE(INR)": r2(mnet),
            f"{mon} MID ACTUAL SALE(INR)": r2(f.m_mid), f"{mon} % ACH": r2(pct(mnet, f.m_tgt)),
            f"{mon} % GROWTH": r2(growth(f.m_act, f.m_ly)), f"{mon} LYR": r2(f.m_ly),
            f"{mon} PCPM": r2(per(f.m_act, hc))}


def hq_level(abm, hcs, k, mon, expiry) -> Sheet:
    """Each division's HQs (those with a target this month), a Total under each
    division, All Total."""
    g = Groups(abm, lambda r: (ci(r["pg"]), ci(r["hq"])), lambda r: (r["pg"], r["hq"]))
    sh = Sheet("HQ LEVEL EXPIRY ADJUST" if expiry else "HQ LEVEL", _hq_cols(mon, expiry))
    keys = [key for key in g.keys() if Figures(g.sums[key], k).m_tgt > 0]
    for key in keys:
        g.sums[key].hc = hcs.get(key)
    shown = []
    for div in sorted({key[0] for key in keys}):
        members = [key for key in keys if key[0] == div]
        for key in members:
            pg, hq = g.label[key]
            sh.add(_hq_row(Figures(g.sums[key], k), mon, expiry, {"DIVISION": pg, "HQ": hq}))
        t = total_of(g.sums[key] for key in members)
        sh.add(_hq_row(Figures(t, k), mon, expiry, {"DIVISION": f"{g.label[members[0]][0]} Total"}), "total")
        shown += members
    sh.add(_hq_row(Figures(total_of(g.sums[key] for key in shown), k), mon, expiry,
                   {"DIVISION": "All Total"}), "all")
    return sh


def _brand_cols(first, mon, expiry, month_first=False):
    ytd = ["YTD TARGET(INR)", "YTD ACTUAL SALE(INR)"]
    if expiry:
        ytd += ["YTD EXPIRY ADJUSTED(INR)", "YTD NET SALE(INR)"]
    ytd += ["YTD % ACH", "YTD % GROWTH", "YTD LYR"]
    m = [f"{mon} TARGET(INR)", f"{mon} ACTUAL SALE(INR)"]
    if expiry:
        m += [f"{mon} EXPIRY ADJUSTED(INR)", f"{mon} NET SALE(INR)"]
    m += [f"{mon} % ACH", f"{mon} % GROWTH", f"{mon} LYR"]
    return first + (m + ytd if month_first else ytd + m)


def _brand_row(f: Figures, mon, first: dict, expiry=False):
    ynet, mnet = (f.y_act - f.y_exp, f.m_act - f.m_exp) if expiry else (f.y_act, f.m_act)
    return {**first, "YTD TARGET(INR)": r2(f.y_tgt), "YTD ACTUAL SALE(INR)": r2(f.y_act),
            "YTD EXPIRY ADJUSTED(INR)": r2(f.y_exp), "YTD NET SALE(INR)": r2(ynet),
            "YTD % ACH": r2(pct(ynet, f.y_tgt)), "YTD % GROWTH": r2(growth(f.y_act, f.y_ly)),
            "YTD LYR": r2(f.y_ly), f"{mon} TARGET(INR)": r2(f.m_tgt), f"{mon} ACTUAL SALE(INR)": r2(f.m_act),
            f"{mon} EXPIRY ADJUSTED(INR)": r2(f.m_exp), f"{mon} NET SALE(INR)": r2(mnet),
            f"{mon} % ACH": r2(pct(mnet, f.m_tgt)), f"{mon} % GROWTH": r2(growth(f.m_act, f.m_ly)),
            f"{mon} LYR": r2(f.m_ly)}


def _anything(f: Figures) -> bool:
    return any(abs(x) > 1e-12 for x in (f.y_tgt, f.y_act, f.y_ly, f.m_tgt, f.m_act, f.m_ly))


def brand_level(abm, k, mon) -> Sheet:
    """Each brand's SKUs, a Total under each brand that has any figure, All Total."""
    g = Groups(abm, lambda r: (ci(r["brand"]), r["pid"]), lambda r: (r["brand"], r["product"]))
    for key in g.sums:                            # MAX(PRODUCT_NAME), as the old query
        names = [r["product"] for r in abm if (ci(r["brand"]), r["pid"]) == key and r["product"]]
        g.label[key] = (g.label[key][0], max(names, key=ci) if names else None)
    sh = Sheet("BRAND LEVEL", _brand_cols(["BRAND", "PRODUCT"], mon, False))
    for brand in sorted({key[0] for key in g.sums}):
        members = sorted((key for key in g.sums if key[0] == brand),
                         key=lambda key: (ci(g.label[key][1]), key[1] or 0))
        for key in members:
            b, p = g.label[key]
            sh.add(_brand_row(Figures(g.sums[key], k), mon, {"BRAND": b, "PRODUCT": p}))
        t = Figures(total_of(g.sums[key] for key in members), k)
        if _anything(t):
            sh.add(_brand_row(t, mon, {"BRAND": f"{g.label[members[0]][0]} Total"}), "total")
    sh.add(_brand_row(Figures(total_of(g.sums.values()), k), mon, {"BRAND": "All Total"}), "all")
    return sh


def brand_level_expiry(abm, k, mon) -> Sheet:
    g = Groups(abm, lambda r: (ci(r["pg"]), ci(r["brand"])), lambda r: (r["pg"], r["brand"]))
    sh = Sheet("BRAND LEVEL EXPIRY ADJUST", _brand_cols(["DIVISION", "BRAND"], mon, True))
    for key in g.keys():
        pg, b = g.label[key]
        sh.add(_brand_row(Figures(g.sums[key], k), mon, {"DIVISION": pg, "BRAND": b}, True))
    sh.add(_brand_row(Figures(total_of(g.sums.values()), k), mon, {"DIVISION": "Total"}, True), "total")
    return sh


def hq_brand_level(abm, k, mon) -> Sheet:
    """Each division and HQ's brands and SKUs, a Total under each HQ, one
    under each division, All Total."""
    g = Groups(abm, lambda r: (ci(r["pg"]), ci(r["hq"]), ci(r["product"]), ci(r["brand"])),
               lambda r: (r["pg"], r["hq"], r["brand"], r["product"]))
    sh = Sheet("HQ and BRAND LEVEL", _brand_cols(["DIVISION", "HQ", "BRAND", "PRODUCT"], mon, False,
                                                 month_first=True))
    for div in sorted({key[0] for key in g.sums}):
        in_div = [key for key in g.sums if key[0] == div]
        for hq in sorted({key[1] for key in in_div}):
            members = sorted(key for key in in_div if key[1] == hq)
            for key in members:
                pg, h, b, p = g.label[key]
                sh.add(_brand_row(Figures(g.sums[key], k), mon,
                                  {"DIVISION": pg, "HQ": h, "BRAND": b, "PRODUCT": p}))
            t = Figures(total_of(g.sums[key] for key in members), k)
            pg, h = g.label[members[0]][:2]
            if _anything(t):
                sh.add(_brand_row(t, mon, {"DIVISION": pg, "HQ": f"{h} - {pg} Total"}), "total")
        t = Figures(total_of(g.sums[key] for key in in_div), k)
        if _anything(t):
            sh.add(_brand_row(t, mon, {"DIVISION": f"{g.label[in_div[0]][0]} Total"}), "total")
    sh.add(_brand_row(Figures(total_of(g.sums.values()), k), mon, {"DIVISION": "All Total"}), "all")
    return sh


def _all_cols(first, head_count):
    c = list(first) + (["HEAD COUNT"] if head_count else [])
    c += ["YTD TARGET(INR)", "YTD ACTUAL SALE(INR)", "YTD % ACH", "YTD % GROWTH", "YTD LYR"]
    c += (["YTD PCPM"] if head_count else []) + ["YTD RETURN"]
    for m in UP:
        c += [f"{m} TARGET(INR)", f"{m} ACTUAL SALE(INR)", f"{m} % ACH", f"{m} % GROWTH", f"{m} LYR"]
        c += ([f"{m} PCPM"] if head_count else []) + [f"{m} RETURN"]
    return c


def _all_row(f: Figures, first: dict):
    hc = f.s.hc
    row = {**first, "HEAD COUNT": hc, "YTD TARGET(INR)": r2(f.y_tgt), "YTD ACTUAL SALE(INR)": r2(f.y_act),
           "YTD % ACH": r2(pct(f.y_act, f.y_tgt)), "YTD % GROWTH": r2(growth(f.y_act, f.y_ly)),
           "YTD LYR": r2(f.y_ly), "YTD PCPM": r2(per(f.y_act, hc)), "YTD RETURN": r2(f.y_ret)}
    for i, m in enumerate(UP, start=1):
        t, a, ly = f.mon("tgt", LAKH, i), f.mon("act", INR, i), f.mon("ly", INR, i)
        row.update({f"{m} TARGET(INR)": r2(t), f"{m} ACTUAL SALE(INR)": r2(a), f"{m} % ACH": r2(pct(a, t)),
                    f"{m} % GROWTH": r2(growth(a, ly)), f"{m} LYR": r2(ly),
                    f"{m} PCPM": r2(per(a, hc)), f"{m} RETURN": r2(f.mon("ret", LAKH, i))})
    return row


def all_hq_level(abm, hcs, k) -> Sheet:
    """Every month side by side for each division's HQs (those with a YTD
    target), a Total under each division, All Total."""
    g = Groups(abm, lambda r: (ci(r["pg"]), ci(r["hq"])), lambda r: (r["pg"], r["hq"]))
    keys = [key for key in g.keys() if Figures(g.sums[key], k).y_tgt > 0]
    for key in keys:
        g.sums[key].hc = hcs.get(key)
    sh = Sheet("ALL HQ LEVEL", _all_cols(["DIVISION", "HQ"], True))
    for div in sorted({key[0] for key in keys}):
        members = [key for key in keys if key[0] == div]
        for key in members:
            pg, hq = g.label[key]
            sh.add(_all_row(Figures(g.sums[key], k), {"DIVISION": pg, "HQ": hq}))
        sh.add(_all_row(Figures(total_of(g.sums[key] for key in members), k),
                        {"DIVISION": f"{g.label[members[0]][0]} Total"}), "total")
    sh.add(_all_row(Figures(total_of(g.sums[key] for key in keys), k), {"DIVISION": "All Total"}), "all")
    return sh


def all_brand_level(abm, k) -> Sheet:
    g = Groups(abm, lambda r: (ci(r["pg"]), ci(r["brand"])), lambda r: (r["pg"], r["brand"]))
    sh = Sheet("ALL BRAND LEVEL", _all_cols(["DIVISION", "BRAND"], False))
    for key in g.keys():
        pg, b = g.label[key]
        sh.add(_all_row(Figures(g.sums[key], k), {"DIVISION": pg, "BRAND": b}))
    sh.add(_all_row(Figures(total_of(g.sums.values()), k), {"DIVISION": "Total"}), "total")
    return sh


CATS = [("P1", "P1"), ("P2", "P2"), ("OTHERS", "X-OTHERS")]


def employee_performance(rows, k, mon) -> Sheet:
    """Each division's TBMs (by HQ), its ABM after them, and the ABMs' Total."""
    cols = ["DIVISION", "EMPLOYEE ID", "EMPLOYEE CODE", "EMPLOYEE NAME", "DESIGNATION", "HQ", "JOINING DATE"]
    for lab, _ in CATS:
        cols += [f"YTD TARGET {lab}", f"YTD ACTUAL SALE {lab}", f"YTD {lab} % ACH"]
    cols += ["YTD TARGET TOTAL", "YTD ACTUAL SALE TOTAL", "YTD TOTAL % ACH"]
    for lab, _ in CATS:
        cols += [f"{mon} TARGET {lab}", f"{mon} ACTUAL SALE {lab}", f"{mon} {lab} % ACH"]
    cols += [f"{mon} TOTAL TARGET", f"{mon} TOTAL ACTUAL SALE", f"{mon} TOTAL % ACH"]
    sh = Sheet("EMPLOYEE SALES PERFORMANCE", cols)

    def sums(rs):
        by = {lab: total_of(r["sums"] for r in rs if ci(r["cat"]) == ci(cat)) for lab, cat in CATS}
        by["TOTAL"] = total_of(r["sums"] for r in rs)
        return by

    def figures(by, first):
        row = dict(first)
        for lab in ("P1", "P2", "OTHERS", "TOTAL"):
            f = Figures(by[lab], k)
            row.update({f"YTD TARGET {lab}": r2(f.y_tgt), f"YTD ACTUAL SALE {lab}": r2(f.y_act),
                        f"YTD {lab} % ACH": r2(pct(f.y_act, f.y_tgt))})
            mt, ma = f"{mon} TARGET {lab}", f"{mon} ACTUAL SALE {lab}"
            if lab == "TOTAL":
                mt, ma = f"{mon} TOTAL TARGET", f"{mon} TOTAL ACTUAL SALE"
            row.update({mt: r2(f.m_tgt), ma: r2(f.m_act), f"{mon} {lab} % ACH": r2(pct(f.m_act, f.m_tgt))})
        return row

    def person(r, hq):
        name = " ".join(f"{r['ft'] or ''} {r['lt'] or ''}".split())
        return {"EMPLOYEE ID": r["emp"], "EMPLOYEE CODE": r["code"], "EMPLOYEE NAME": name,
                "DESIGNATION": r["desig_name"], "HQ": hq,
                "JOINING DATE": r["start"].strftime("%d/%m/%Y") if r["start"] else None}

    def grouped(rs, key):
        out: dict = {}
        for r in rs:
            out.setdefault(key(r), []).append(r)
        return out

    tbm = grouped([r for r in rows if r["desig"] == TBM], lambda r: (ci(r["pg"]), ci(r["hq"]), r["emp"]))
    abm = grouped([r for r in rows if r["desig"] == ABM], lambda r: (ci(r["pg"]), r["emp"]))
    live = lambda rs: Figures(total_of(r["sums"] for r in rs), k).m_tgt > 0       # noqa: E731
    tbm = {key: rs for key, rs in tbm.items() if live(rs)}
    abm = {key: rs for key, rs in abm.items() if live(rs)}
    for div in sorted({key[0] for key in tbm} | {key[0] for key in abm}):
        for key in sorted(key for key in tbm if key[0] == div):
            rs = tbm[key]
            sh.add(figures(sums(rs), {"DIVISION": rs[0]["pg"], **person(rs[0], rs[0]["hq"])}))
        for key in sorted(key for key in abm if key[0] == div):
            rs = abm[key]
            sh.add(figures(sums(rs), {"DIVISION": rs[0]["pg"], **person(rs[0], "Kathmandu")}))
    every = [r for rs in abm.values() for r in rs]
    sh.add(figures(sums(every), {"DIVISION": "All Total(Rahul Dharwad)"}), "all")
    return sh


# ============================================================ sales queries
class Run:
    """SQL on this database. MySQL compares MONTH case-blind by itself; SQLite
    (the tests) is told to."""

    def __init__(self, db: Session):
        self.db = db
        self.mysql = db.get_bind().dialect.name in ("mysql", "mariadb")

    def rows(self, sql: str, **binds) -> list[dict]:
        if not self.mysql:
            sql = sql.replace("MONTH = :month", "MONTH = :month COLLATE NOCASE")
        res = self.db.execute(text(sql), binds)
        return [dict(r._mapping) for r in res]


Q0 = "COALESCE({0}, 0)"
SALES_KEYS = ("DIST_ID, DIST_NAME, CUSTOMER_ID, CUSTOMER_MASTER_NAME, PRODUCT_GROUP_ID, PRODUCT_GROUP_NAME, "
              "PRODUCT_BRAND_NAME, PRODUCT_BRAND_CATEGORY, PRODUCT_ID, PRODUCT_MASTER_NAME, HQ_ID, HQ_NAME, "
              "RATE, MONTH, YEAR")
SALES_SQL = f"""
SELECT {SALES_KEYS},
  SUM(COALESCE(SALES_QTY, 0)) AS q, SUM(COALESCE(FREE_QUANTITY, 0)) AS f,
  SUM(COALESCE(RETURN_QUANTITY, 0)) AS r,
  SUM((COALESCE(SALES_QTY, 0) + COALESCE(RETURN_QUANTITY, 0)) * RATE) AS v
FROM {{table}} WHERE YEAR = :year AND MONTH = :month
GROUP BY {SALES_KEYS}
ORDER BY PRODUCT_GROUP_NAME, HQ_NAME, DIST_ID, DIST_NAME, CUSTOMER_ID, CUSTOMER_MASTER_NAME,
  PRODUCT_GROUP_ID, PRODUCT_BRAND_NAME, PRODUCT_BRAND_CATEGORY, PRODUCT_ID, PRODUCT_MASTER_NAME, HQ_ID, RATE
"""
EXPIRY_KEYS = ("DIST_ID, DIST_NAME, CUSTOMER_ID, CUSTOMER_MASTER_NAME, PRODUCT_GROUP_ID, PRODUCT_GROUP_NAME, "
               "PRODUCT_BRAND_ID, PRODUCT_BRAND_NAME, PRODUCT_ID, PRODUCT_MASTER_NAME, PRODUCT_BRAND_CATEGORY, "
               "HQ_ID, HQ_NAME, RATE, MONTH, YEAR")
EXPIRY_SQL = f"""
SELECT {EXPIRY_KEYS},
  SUM(COALESCE(SALES_QTY, 0)) AS q, SUM(COALESCE(FREE_QUANTITY, 0)) AS f,
  SUM(COALESCE(RETURN_QUANTITY, 0)) AS r, SUM(COALESCE(AMOUNT, 0)) AS amount,
  SUM(COALESCE(CUSTOM_CHARGE, 0)) AS charge, SUM(COALESCE(TOTAL_AMOUNT, 0)) AS total
FROM MAPPING_MASTER_EXPIRY WHERE YEAR = :year AND MONTH = :month
GROUP BY {EXPIRY_KEYS}
ORDER BY PRODUCT_GROUP_NAME, HQ_NAME, DIST_ID, DIST_NAME, CUSTOMER_ID, CUSTOMER_MASTER_NAME,
  PRODUCT_GROUP_ID, PRODUCT_BRAND_ID, PRODUCT_BRAND_NAME, PRODUCT_ID, PRODUCT_MASTER_NAME, HQ_ID, RATE
"""
ADJ_KEYS = ("DIST_ID, DIST_NAME, CUSTOMER_ID, CUSTOMER_MASTER_NAME, PRODUCT_GROUP_ID, PRODUCT_GROUP_NAME, "
            "PRODUCT_BRAND_ID, PRODUCT_BRAND_NAME, PRODUCT_ID, PRODUCT_MASTER_NAME, PRODUCT_BRAND_CATEGORY, "
            "HQ_ID, HQ_NAME, RATE, MONTH, YEAR, ADJUSTED_MONTH")
ADJ_SQL = f"""
SELECT {ADJ_KEYS},
  SUM(COALESCE(SALES_QTY, 0)) AS q, SUM(COALESCE(FREE_QUANTITY, 0)) AS f,
  SUM(COALESCE(EXPIRY_TOTAL_AMOUNT, 0)) AS amount
FROM ADJUSTMENT WHERE YEAR = :year AND MONTH = :month
GROUP BY {ADJ_KEYS}
ORDER BY CUSTOMER_ID, DIST_ID, DIST_NAME, CUSTOMER_MASTER_NAME, PRODUCT_GROUP_ID, PRODUCT_BRAND_ID,
  PRODUCT_ID, HQ_ID, RATE, ADJUSTED_MONTH
"""
SALES_MONTHS_SQL = """
SELECT MONTH AS m, SUM((COALESCE(SALES_QTY, 0) + COALESCE(RETURN_QUANTITY, 0)) * RATE) AS v
FROM MAPPING_MASTER WHERE YEAR = :year GROUP BY MONTH
"""
EXPIRY_MONTHS_SQL = """
SELECT MONTH AS m, SUM(COALESCE(EXPIRY_TOTAL_AMOUNT, 0)) AS v FROM ADJUSTMENT WHERE YEAR = :year GROUP BY MONTH
"""
DIST_SQL = """
SELECT DIST_NAME AS d,
  SUM(CASE WHEN MONTH = :month THEN (COALESCE(SALES_QTY, 0) + COALESCE(RETURN_QUANTITY, 0)) * RATE ELSE 0 END) AS v
FROM MAPPING_MASTER WHERE YEAR = :year GROUP BY DIST_NAME ORDER BY DIST_NAME
"""
DIST_EXPIRY_SQL = """
SELECT DIST_NAME AS d, SUM((COALESCE(SALES_QTY, 0) + COALESCE(RETURN_QUANTITY, 0)) * RATE) AS v
FROM MAPPING_MASTER_EXPIRY WHERE YEAR = :year AND MONTH = :month GROUP BY DIST_NAME
"""
DIST_ADJ_SQL = """
SELECT DIST_NAME AS d, SUM(COALESCE(EXPIRY_TOTAL_AMOUNT, 0)) AS v
FROM ADJUSTMENT WHERE YEAR = :year AND MONTH = :month GROUP BY DIST_NAME
"""


def _monthly(run: Run, sql, year) -> list[float]:
    out = [0.0] * 12
    for r in run.rows(sql, year=year):
        m = ci(r["m"]).upper()
        if m in UP:
            out[UP.index(m)] += _n(r["v"])
    return out


def nepal_level(run: Run, abm, year, expiry) -> Sheet:
    """Every month's target and sale, and the year to date (month by month,
    not only up to the month asked, as the old sheet)."""
    tgt = total_of(r["sums"] for r in abm).tgt
    sale = _monthly(run, SALES_MONTHS_SQL, year)
    exp = _monthly(run, EXPIRY_MONTHS_SQL, year) if expiry else [0.0] * 12
    cols = ["MONTH", "MONTH TARGET", "MONTH SALE"]
    cols += (["EXPIRY ADJUSTED", "NET SALE", "MONTH % ACH", "YTD TARGET", "YTD SALE", "YTD EXPIRY",
              "YTD SALE(AFTER EXPIRY)", "YTD % ACH(AFTER EXPIRY ADJSTMENT)"] if expiry
             else ["MONTH % ACH", "YTD TARGET", "YTD SALE", "YTD % ACH"])
    sh = Sheet("NEPAL LEVEL EXPIRY ADJUST" if expiry else "NEPAL LEVEL", cols)
    for i, m in enumerate(UP):
        mt, ms, me = tgt[i] / LAKH, sale[i] / (INR * LAKH), exp[i] / (INR * LAKH)
        yt = sum(tgt[:i + 1]) / LAKH
        ys, ye = sum(sale[:i + 1]) / (INR * LAKH), sum(exp[:i + 1]) / (INR * LAKH)
        sh.add({"MONTH": m, "MONTH TARGET": r2(mt), "MONTH SALE": r2(ms), "EXPIRY ADJUSTED": r2(me),
                "NET SALE": r2(ms - me), "MONTH % ACH": r2(pct(ms - me, mt)), "YTD TARGET": r2(yt),
                "YTD SALE": r2(ys), "YTD EXPIRY": r2(ye), "YTD SALE(AFTER EXPIRY)": r2(ys - ye),
                "YTD % ACH": r2(pct(ys, yt)), "YTD % ACH(AFTER EXPIRY ADJSTMENT)": r2(pct(ys - ye, yt))})
    return sh


def distributor_level(run: Run, year, month, adjusted) -> Sheet:
    """Every distributor with sales in the year: the month's sales and its
    expiry (from MAPPING_MASTER_EXPIRY, or as adjusted, from ADJUSTMENT)."""
    if adjusted:
        name, c1, c2, sql = ("DISTRIBUTOR LEVEL EXPIRY ADJUST", "EXPIRY VALUE(INR) ADJUATED",
                             "EXPIRY VALUE ADJUSTED(NPR)", DIST_ADJ_SQL)
    else:
        name, c1, c2, sql = "DISTRIBUTOR LEVEL", "EXPIRY VALUE(INR)", "EXPIRY VALUE(NPR)", DIST_EXPIRY_SQL
    sh = Sheet(name, ["DISTRIBUTOR NAME", "SALES VALUE(INR)", "SALES VALUE(NPR)", c1, c2])
    exp: dict = {}
    for r in run.rows(sql, year=year, month=month):
        exp[ci(r["d"])] = exp.get(ci(r["d"]), 0.0) + _n(r["v"])
    tv = te = 0.0
    for r in run.rows(DIST_SQL, year=year, month=month):
        v, e = _n(r["v"]), exp.get(ci(r["d"]), 0.0)
        tv, te = tv + v, te + e
        sh.add({"DISTRIBUTOR NAME": r["d"], "SALES VALUE(INR)": r2(v / INR / LAKH),
                "SALES VALUE(NPR)": r2(v / LAKH), c1: r2(e / INR / LAKH), c2: r2(e / LAKH)})
    sh.add({"DISTRIBUTOR NAME": "Total", "SALES VALUE(INR)": r2(tv / INR / LAKH), "SALES VALUE(NPR)": r2(tv / LAKH),
            c1: r2(te / INR / LAKH), c2: r2(te / LAKH)}, "total")
    return sh


SALES_COLS = ["DISTRIBUTOR ID", "DISTRIBUTOR", "CUSTOMER ID", "CUSTOMER NAME", "DIVISION ID", "DIVISION", "BRAND",
              "PRODUCT CATEGORY", "SKU ID", "SKU", "HQ ID", "HQ NAME", "SALES QTY", "FREE QTY", "RETURN QTY",
              "TOTAL QTY", "RATE"]


def _who(r):
    return {"DISTRIBUTOR ID": r["DIST_ID"], "DISTRIBUTOR": r["DIST_NAME"], "CUSTOMER ID": r["CUSTOMER_ID"],
            "CUSTOMER NAME": r["CUSTOMER_MASTER_NAME"], "DIVISION ID": r["PRODUCT_GROUP_ID"],
            "DIVISION": r["PRODUCT_GROUP_NAME"], "BRAND": r["PRODUCT_BRAND_NAME"],
            "PRODUCT CATEGORY": r["PRODUCT_BRAND_CATEGORY"], "SKU ID": r["PRODUCT_ID"],
            "SKU": r["PRODUCT_MASTER_NAME"], "HQ ID": r["HQ_ID"], "HQ NAME": r["HQ_NAME"],
            "MONTH": r["MONTH"], "YEAR": r["YEAR"]}


def sales_sheet(name, rows, label, names=None) -> Sheet:
    cols = SALES_COLS + ["SALES VALUE(INR)", "SALES VALUE(NPR)", "MONTH", "YEAR"]
    sh = Sheet(name, cols + (["EMPLOYEE NAME", "TEAM"] if names is not None else []))
    tv = 0.0
    for r in rows:
        q, f, ret, v = _n(r["q"]), _n(r["f"]), _n(r["r"]), _n(r["v"])
        tv += v
        row = {**_who(r), "SALES QTY": q, "FREE QTY": f, "RETURN QTY": ret, "TOTAL QTY": q + f + ret,
               "RATE": r2(_n(r["RATE"]) / INR), "SALES VALUE(INR)": r2(v / INR), "SALES VALUE(NPR)": r2(v)}
        if names is not None:
            row.update(dict(zip(("EMPLOYEE NAME", "TEAM"), names.get((ci(r["PRODUCT_GROUP_NAME"]),
                                                                        ci(r["HQ_NAME"])), (None, None)))))
        sh.add(row)
    sh.add({"DISTRIBUTOR ID": label, "SALES VALUE(INR)": r2(tv / INR), "SALES VALUE(NPR)": r2(tv)}, "total")
    return sh


def expiry_sheet(name, rows, label, names=None) -> Sheet:
    cols = SALES_COLS + ["EXPIRY AMOUNT(INR)", "CUSTOM CHARGE(INR)", "TOTAL AMOUNT(INR)", "MONTH", "YEAR"]
    sh = Sheet(name, cols + (["EMPLOYEE NAME", "TEAM"] if names is not None else []))
    ta = tt = 0.0
    for r in rows:
        q, f, ret = _n(r["q"]), _n(r["f"]), _n(r["r"])
        a, c, t = _n(r["amount"]), _n(r["charge"]), _n(r["total"])
        ta, tt = ta + a, tt + t
        row = {**_who(r), "SALES QTY": q, "FREE QTY": f, "RETURN QTY": ret, "TOTAL QTY": q + f - ret,
               "RATE": r2(_n(r["RATE"]) / INR), "EXPIRY AMOUNT(INR)": r2(a / INR),
               "CUSTOM CHARGE(INR)": r2(c / INR), "TOTAL AMOUNT(INR)": r2(t / INR)}
        if names is not None:
            row.update(dict(zip(("EMPLOYEE NAME", "TEAM"), names.get((ci(r["PRODUCT_GROUP_NAME"]),
                                                                        ci(r["HQ_NAME"])), (None, None)))))
        sh.add(row)
    sh.add({"DISTRIBUTOR ID": label, "EXPIRY AMOUNT(INR)": r2(ta / INR), "TOTAL AMOUNT(INR)": r2(tt / INR)},
           "total")
    return sh


def sales_adjustment(adj_rows, sales_rows) -> Sheet:
    """The month's ADJUSTMENT rows and its sales side by side, by customer
    (ADJUSTMENT's first where they tie)."""
    sh = Sheet("SALES ADJUSTMENT", ["DISTRIBUTOR ID", "DISTRIBUTOR", "CUSTOMER ID", "CUSTOMER NAME", "DIVISION ID",
                                    "DIVISION", "BRAND", "PRODUCT CATEGORY", "SKU ID", "SKU", "HQ ID", "HQ NAME",
                                    "SALES QTY", "ADJUSTED SALE QTY", "FREE QTY", "ADJUSTED FREE QTY",
                                    "RETURN QTY", "RATE", "ADJUSTED RATE", "AMOUNT", "ADJUSTED AMOUNT", "MONTH",
                                    "YEAR", "ADJUSTED MONTH"])
    both = [(0, r) for r in adj_rows] + [(1, r) for r in sales_rows]
    both.sort(key=lambda x: (x[1]["CUSTOMER_ID"] is not None, x[1]["CUSTOMER_ID"] or 0, x[0]))
    ta = tadj = 0.0
    for kind, r in both:
        row = {**_who(r), "SALES QTY": 0.0, "ADJUSTED SALE QTY": 0.0, "FREE QTY": 0.0, "ADJUSTED FREE QTY": 0.0,
               "RETURN QTY": 0.0, "RATE": 0.0, "ADJUSTED RATE": 0.0, "AMOUNT": 0.0, "ADJUSTED AMOUNT": 0.0,
               "ADJUSTED MONTH": r.get("ADJUSTED_MONTH")}
        if kind == 0:
            amount = _n(r["amount"])
            tadj += amount
            row.update({"ADJUSTED SALE QTY": _n(r["q"]), "ADJUSTED FREE QTY": _n(r["f"]),
                        "ADJUSTED RATE": r2(_n(r["RATE"]) / INR), "ADJUSTED AMOUNT": r2(amount / INR)})
        else:
            v = _n(r["v"])
            ta += v
            row.update({"SALES QTY": _n(r["q"]), "FREE QTY": _n(r["f"]), "RETURN QTY": _n(r["r"]),
                        "RATE": r2(_n(r["RATE"]) / INR), "AMOUNT": r2(v / INR)})
        sh.add(row)
    sh.add({"DISTRIBUTOR ID": "Total Adjustment Sale", "AMOUNT": r2(ta / INR), "ADJUSTED AMOUNT": r2(tadj / INR)},
           "total")
    return sh


def employee_names(db: Session) -> dict:
    """(division, HQ) -> ("First Last,First Last", division): the active
    employees given that product group and that HQ, in first-name order. One
    query for all, where the old page asked once per sales row."""
    res = db.execute(text(
        "SELECT DISTINCT PG.Name, HQ.Name, EM.EMPLOYEE_ID, EM.EMPLOYEE_FT_NM, EM.EMPLOYEE_LT_NM "
        "FROM EMPLOYEE_PG_ASSIGNMENT EPA "
        "INNER JOIN md_product_group PG ON PG.LegacyId = EPA.PRODUCT_GROUP_ID "
        "INNER JOIN EMPLOYEE_MASTER EM ON EM.EMPLOYEE_ID = EPA.EMPLOYEE_ID "
        "INNER JOIN EMPLOYEE_TERR_ASSIGNMENT ETA ON ETA.EMPLOYEE_ID = EM.EMPLOYEE_ID "
        "INNER JOIN md_headquarter HQ ON HQ.LegacyId = ETA.HQ_ID "
        "WHERE EM.STATUS = 1"))
    found: dict = {}
    for pg, hq, emp, ft, lt in res:
        e = found.setdefault((ci(pg), ci(hq)), {"pg": pg, "people": {}})
        e["people"][emp] = (ft or "", " ".join(f"{ft or ''} {lt or ''}".split()))
    return {k: (",".join(n for _, n in sorted(e["people"].values(), key=lambda p: (ci(p[0]), ci(p[1])))),
                e["pg"]) for k, e in found.items()}


# ===================================================================== build
def build(db: Session, month: str, year: int) -> list[Sheet]:
    if month not in MONTHS:
        raise ValueError(f"{month} is not a month")
    year = int(year)
    k = MONTHS.index(month) + 1
    run = Run(db)
    budget = read_budget(db, year)
    abm = [r for r in budget if r["desig"] == ABM]
    hcs = head_counts(db)
    names = employee_names(db)
    sales = run.rows(SALES_SQL.format(table="MAPPING_MASTER"), year=year, month=month)
    mid = run.rows(SALES_SQL.format(table="MAPPING_MASTER_MID"), year=year, month=month)
    expiry = run.rows(EXPIRY_SQL, year=year, month=month)
    adj = run.rows(ADJ_SQL, year=year, month=month)
    return [
        nepal_level(run, [r for r in abm if r["year"] == year], year, False),
        nepal_level(run, [r for r in abm if r["year"] == year], year, True),
        distributor_level(run, year, month, False), distributor_level(run, year, month, True),
        hq_level(abm, hcs, k, month, False), hq_level(abm, hcs, k, month, True),
        brand_level(abm, k, month), brand_level_expiry(abm, k, month), hq_brand_level(abm, k, month),
        all_hq_level(abm, hcs, k), all_brand_level(abm, k),
        employee_performance([r for r in budget if r["year"] == year], k, month),
        sales_sheet("SALES", sales, "Total Sale"), sales_sheet("SALES MID", mid, "Total Mid Sale"),
        sales_sheet("EMPLOYEE SALES", sales, "Total Employee Sale", names),
        expiry_sheet("EXPIRY SALES", expiry, "Total Expiry Sale"),
        expiry_sheet("EMPLOYEE EXPIRY SALES", expiry, "Total Employee Expiry Sale", names),
        sales_adjustment(adj, sales),
    ]


# ================================================================ the workbook
# The old file's look: Georgia 9, thin borders, a baby-blue bold heading, Total
# rows light green, All Total pink. Written with XlsxWriter, which is several
# times quicker than openpyxl for a sheet of thousands of styled cells.
BABY_BLUE, LIGHT_GREEN, BABY_PINK = "#89CFF0", "#90EE90", "#F4C2C2"
_DIGITS = re.compile(r"^\d{1,15}$")


def _cell_value(v):
    """Numbers as numbers (a code made of digits too, as the old file had
    them); whole numbers without .0."""
    if isinstance(v, str):
        s = v.strip()
        return int(s) if _DIGITS.match(s) else v
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    return v


@lru_cache(maxsize=65536)
def _width(s: str) -> float:
    """Roughly how wide Excel needs a column for this text in Georgia 9."""
    w = 0.0
    for ch in s:
        w += 0.55 if ch in " .,:;'|!il1" else 0.85 if ch.islower() else 1.05
    return w


def workbook(sheets: list[Sheet]) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False})
    base = {"font_name": "Georgia", "font_size": 9, "border": 1}
    fmt: dict = {}

    def look(fill, align, bold=False):
        key = (fill, align, bold)
        if key not in fmt:
            f = dict(base, bold=bold)
            if fill:
                f.update(pattern=1, bg_color=fill)
            if align:
                f["align"] = align
            fmt[key] = wb.add_format(f)
        return fmt[key]

    for sh in sheets:
        ws = wb.add_worksheet(sh.name)
        widths = [_width(c) * 1.08 for c in sh.columns]
        for j, c in enumerate(sh.columns):
            ws.write_string(0, j, c, look(BABY_BLUE, None, True))
        for i, (row, kind) in enumerate(zip(sh.rows, sh.kinds), start=1):
            fill = BABY_PINK if kind == "all" else LIGHT_GREEN if kind == "total" else None
            for j, v in enumerate(row):
                if v is None or v == "":
                    ws.write_blank(i, j, None, look(fill, None))
                    continue
                v = _cell_value(v)
                if isinstance(v, str):
                    ws.write_string(i, j, v, look(fill, "left"))
                    w = _width(v)
                else:
                    ws.write_number(i, j, v, look(fill, "right"))
                    w = len(str(v)) * 1.05
                if w > widths[j]:
                    widths[j] = w
        for j, w in enumerate(widths):
            ws.set_column(j, j, round(w + 2.0, 2))
    wb.close()
    return buf.getvalue()


def report(db: Session, month: str, year: int) -> tuple[str, bytes]:
    return file_name(month, year), workbook(build(db, month, year))
