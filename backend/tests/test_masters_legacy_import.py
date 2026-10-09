"""The old SQL Server masters come across whole, and a second run changes nothing."""
import io

import pytest
from openpyxl import Workbook

from tests.harness import client as c, ok, sign_in


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


def xlsx(head, *rows):
    wb = Workbook()
    ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append(list(r))
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


ALIAS = [f"PRODUCT_ALIAS_{i}" for i in range(1, 101)]
CALIAS = [f"CUSTOMER_ALIAS_{i}" for i in range(1, 51)]


def product(pid, name, brand, group, sap, *aliases):
    al = list(aliases) + [None] * (100 - len(aliases))
    return [pid, name, *al, brand, group, sap, "12.5", "2019-01-01", "2099-12-31", 1, f"M{pid}"]


def files():
    return [
        ("PRODUCT_MASTER_GROUP.xlsx", xlsx(["PRODUCT_GROUP_ID", "PRODUCT_GROUP_NAME", "STATUS"],
                                           (1, "GASTRO", 1), (8, "PAIN", 1))),
        ("PRODUCT_MASTER_BRAND.xlsx", xlsx(
            ["PRODUCT_BRAND_ID", "PRODUCT_BRAND_NAME", "PRODUCT_GROUP_ID", "START_DATE", "END_DATE",
             "STATUS", "REPORTING", "TEAM_ID", "NRV", "NO_OF_SKU"],
            (2, "HEPTRAL", 1, "2019-01-01", "2099-12-31", 1, "X-OTHERS", "NULL", "NULL", 1),
            (5, "DUPHASTON", 1, "2019-01-01", "2099-12-31", 1, "P1", None, None, 1),
            (14, "BRUFEN", 8, "2019-01-01", "2099-12-31", 0, "P2", None, None, 3))),
        ("PRODUCT_MASTER.xlsx", xlsx(
            ["PRODUCT_ID", "SAP_PRODUCT_NAME", *ALIAS, "PRODUCT_BRAND_ID", "PRODUCT_GROUP_ID",
             "SAP_PRODUCT_ID", "NRV", "START_DATE", "END_DATE", "STATUS", "MATERIAL_CODE"],
            product(10, "HEPTRAL 400MG TAB 10S", 2, 1, "SAP10", "HEPTRAL 400", "HEPTRAL TAB", ""),
            product(11, "BRUFEN 400 TAB", 14, 8, "SAP11", "BRUFEN-400"),
            product(12, "BRUFEN SYRUP", 14, 8, None),
            product(13, "LOST BRAND SKU", 99, 8, "SAP13"))),
        ("CUSTOMER_MASTER.csv", (",".join(
            ["CUSTOMER_ID", "CUSTOMER_NAME", "CUSTOMER_SAP_ID", "ZONE_ID", "HQ_ID", "TERRITORY_ID",
             "SUB_TERRITORY_ID", "CUSTOMER_BILLING_NAME", "STATE_ID", "CUST_CLASSIFICATION_ID",
             "CUST_REMARK_ID", *CALIAS, "START_DATE", "END_DATE", "STATUS"]) + "\n" +
            ",".join(["501", "Shree Medicals", "CS501", "1", "7", "70", "NULL", "Shree Medical Hall",
                      "3", "2", "NULL", "SHREE MED", "SHRI MEDICALS", *[""] * 48,
                      "2019-01-01", "2099-12-31", "1"]) + "\n").encode()),
        ("CUST_CLASSIFICATION.csv", b"CUST_CLASSIFICATION_ID,CLASSIFICATION_NAME\n2,Chemist\n"),
        ("STATE.csv", b"STATE_ID,STATE_NAME\n3,Bagmati\n"),
        ("ROLE_MASTER.csv", b"ROLE_ID,ROLE_NAME\n1,Admin\n2,Field\n"),
        ("EMPLOYEE_MASTER.xlsx", xlsx(
            ["EMPLOYEE_ID", "EMPLOYEE_FT_NM", "EMPLOYEE_LT_NM", "EMAIL", "PASSWORD", "STATUS",
             "ROLE_ID", "DESIGNATION_ID", "START_DATE", "END_DATE", "TEAM",
             "REPORTING_MANAGER_ID", "RD_CS_EDITABLE", "EMPLOYEE_CODE", "TERRITORY_CODE"],
            (1, "Ram", "Sharma", "ram@x.com", "secret", 1, 1, 4, "2020-01-01", "2099-12-31",
             "Legacy Team", 0, 1, 9001, None),
            (2, "Sita", "Rai", "sita@x.com", "secret", 1, 2, 5, "2021-01-01", "2099-12-31",
             "Legacy Team", 1, 0, None, "T70"))),
    ]


@pytest.fixture(scope="module")
def year(h):
    return ok(c.post("/api/masters/year", headers=h, json=dict(
        year_value=2031, label="Import year", start_date="2031-01-01", end_date="2031-12-31")),
        201)["id"]


def send(h, fs, dry, year_id=None):
    data = {"dry_run": str(dry).lower()}
    if year_id:
        data["year_id"] = str(year_id)
    return ok(c.post("/api/legacy-import", headers=h, data=data,
                     files=[("files", (n, d)) for n, d in fs]))


def rows(h, slug, **p):
    return ok(c.get(f"/api/masters/{slug}", params={"size": 500, **p}, headers=h))["rows"]


def test_dry_run_writes_nothing(h, year):
    before = len(rows(h, "sku"))
    r = send(h, files(), True, year)
    assert r["dry_run"] and r["tables"]["product"]["added"] == 4
    assert len(rows(h, "sku")) == before


def test_import_carries_everything(h, year):
    r = send(h, files(), False, year)
    t = r["tables"]
    assert t["product"]["added"] == 4 and t["product"]["aliases"] == 3
    assert t["customer"]["added"] == 1 and t["customer"]["aliases"] == 2
    assert t["employee"]["added"] == 2
    sku = {s["name"]: s for s in rows(h, "sku")}
    heptral = sku["HEPTRAL 400MG TAB 10S"]
    assert heptral["code"] == "SAP10" and heptral["sap_product_id"] == "SAP10"
    assert heptral["material_code"] == "M10" and heptral["legacy_id"] == 10
    assert sku["BRUFEN SYRUP"]["code"] == "P12"                 # no SAP id: old id
    assert sku["LOST BRAND SKU"]["brand_id__label"].endswith("Brand #99")   # placeholder
    brands = {b["name"]: b for b in rows(h, "brand")}
    assert brands["BRUFEN"]["active"] == 0
    lines = {x["name"]: x for x in rows(h, "product_reporting", year_id=year)}
    assert lines["DUPHASTON"]["flag"] == "P1" and lines["HEPTRAL"]["flag"] == "X"
    assert len(rows(h, "product_reporting_sku", year_id=year)) == 3           # SKUs of flagged brands
    aliases = {a["alias"] for a in rows(h, "sku_alias")}
    assert {"HEPTRAL 400", "HEPTRAL TAB", "BRUFEN-400"} <= aliases

    cust = [x for x in rows(h, "customer") if x["legacy_id"] == 501][0]
    assert cust["code"] == "CS501" and cust["classification"] == "Chemist"
    assert cust["state"] == "Bagmati" and cust["billing_name"] == "Shree Medical Hall"
    assert cust["territory_id__label"].endswith("Territory #70")
    assert {a["alias"] for a in rows(h, "customer_alias")} == {"SHREE MED", "SHRI MEDICALS"}

    emp = {e["name"]: e for e in rows(h, "employee")}
    assert emp["Ram Sharma"]["code"] == "9001" and emp["Ram Sharma"]["rd_cs_editable"] == 1
    assert emp["Sita Rai"]["reports_to_id"] == emp["Ram Sharma"]["id"]
    assert emp["Sita Rai"]["role_id__label"].endswith("Field")
    assert "PASSWORD" not in str(emp)


def test_a_second_run_adds_nothing(h, year):
    counts = {s: len(rows(h, s)) for s in ("sku", "brand", "customer", "employee", "sku_alias",
                                           "customer_alias", "team", "headquarter")}
    r = send(h, files(), False, year)
    assert r["tables"]["product"]["added"] == 0 and r["tables"]["product"]["updated"] == 4
    assert r["tables"]["product"]["aliases"] == 0
    assert {s: len(rows(h, s)) for s in counts} == counts


def test_a_later_file_names_the_placeholders(h):
    send(h, [("HQ_MASTER.csv", b"HQ_ID,HQ_NAME,HQ_CODE,ZONE_ID\n7,Kathmandu,LEG-KTM,1\n"),
             ("TERRITORY.csv", b"TERRITORY_ID,TERRITORY_NAME,HQ_ID\n70,Kathmandu East,7\n")], False)
    hq = [x for x in rows(h, "headquarter") if x["legacy_id"] == 7]
    assert len(hq) == 1 and hq[0]["name"] == "Kathmandu" and hq[0]["code"] == "LEG-KTM"
    cust = [x for x in rows(h, "customer") if x["legacy_id"] == 501][0]
    assert cust["territory_id__label"].endswith("Kathmandu East")


def test_unknown_files_are_left_alone(h):
    r = send(h, [("STOCK_ENTRY.csv", b"A,B\n1,2\n")], True)
    assert r["files"][0]["read_as"] is None
    assert any("not a table" in m for m in r["messages"])
