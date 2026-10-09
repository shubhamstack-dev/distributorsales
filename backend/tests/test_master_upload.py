"""Uploading master data from Excel: MASTER DATA & TABLES.xlsx as it is, the
old system's tables, and any master from its own screen."""
import io
from datetime import datetime

import openpyxl
import pytest

from tests.harness import client as c, ok, sign_in

D0, D1 = datetime(2019, 1, 1), datetime(2099, 12, 31)


def wb_bytes(sheets: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def master_data() -> bytes:
    """The shape of MASTER DATA & TABLES.xlsx: its four sheets, its columns."""
    cust_h = (["CUSTOMER_ID", "CUSTOMER_NAME", "CUSTOMER_SAP_ID", "ZONE_ID", "HQ_ID", "TERRITORY_ID",
               "SUB_TERRITORY_ID", "CUSTOMER_BILLING_NAME", "STATE_ID", "CUST_CLASSIFICATION_ID",
               "CUST_REMARK_ID"] + [f"CUSTOMER_ALIAS_{i}" for i in range(1, 51)]
              + ["START_DATE", "END_DATE", "STATUS"])

    def cust(i, name, aliases, zone="NULL"):
        a = aliases + [None] * (50 - len(aliases))
        return [i, name, "NULL", zone, "NULL", "NULL", "NULL", "NULL", "NULL", 1, "NULL"] + a + [D0, D1, 1]

    prod_h = (["PRODUCT_ID", "SAP_PRODUCT_NAME"] + [f"PRODUCT_ALIAS_{i}" for i in range(1, 101)]
              + ["PRODUCT_BRAND_ID", "PRODUCT_GROUP_ID", "SAP_PRODUCT_ID", "NRV", "START_DATE",
                 "END_DATE", "STATUS", "MATERIAL_CODE"])

    def prod(i, name, aliases, brand, group, sap, nrv, mat="NULL"):
        a = aliases + ["NULL"] * (100 - len(aliases))
        return [i, name] + a + [brand, group, sap, nrv, D0, D1, 1, mat]

    return wb_bytes({
        "CUSTOMER_MASTER": [cust_h,
                            cust(1, "HEALTH MEDECINE DISTRIBUTOR", ["HEALTHMEDECINEDISTRIBUTOR",
                                 "HEALTH MEDICINE DIST NPJ"], zone=0),
                            cust(3, "ICON PHARMA", ["ICONPHARMA", "ICON MEDICINE DISTRIBUTORS"])],
        "EMPLOYEE_MASTER": [["EMPLOYEE_ID", "EMPLOYEE_FT_NM", "EMPLOYEE_LT_NM", "EMAIL", "PASSWORD",
                             "STATUS", "ROLE_ID", "DESIGNATION_ID", "START_DATE", "END_DATE", "TEAM",
                             "REPORTING_MANAGER_ID", "RD_CS_EDITABLE", "EMPLOYEE_CODE",
                             "TERRITORY_CODE"],
                            [29025, "SANTOSH", "PANDEY", "s@x.com", "secret@123", 1, 2, 3, D0, D1,
                             "PRIMARY CARE", 28865, 0, 500004, "IT019942"],
                            [28865, "SANDEEP", "TEMKAR", "t@x.com", "secret@123", 0, 3, 1, D0, D1,
                             "ALL", 28865, 0, 500051, "RG001849"]],
        "PRODUCT_MASTER_BRAND": [["PRODUCT_BRAND_ID", "PRODUCT_BRAND_NAME", "PRODUCT_GROUP_ID",
                                  "START_DATE", "END_DATE", "STATUS", "REPORTING", "TEAM_ID", "NRV",
                                  "NO_OF_SKU"],
                                 [9, "DIGENE", 8, D0, D1, 1, "P2", "NULL", "NULL", 3],
                                 [12, "CREMALAX", 8, D0, D1, 1, "X-OTHERS", "NULL", "NULL", 2]],
        # products sent before brands in the workbook: brands are still read first
        "PRODUCT_MASTER": [prod_h,
                           prod(6, "CREMALAX TAB 10S", ["CREMALAX TAB", "CREMALAX TAB 6 S"], 12, 8,
                                1040000141, 181.4),
                           prod(8, "DIGENE GEL MINT 200ML", ["DIGENE GEL M 200 ML"], 9, 8,
                                1030001557, 130.5, 2030001557)],
    })


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


def send(h, files, dry=True, slug=None):
    data = {"dry_run": "true" if dry else "false"}
    if slug:
        data["slug"] = slug
    return c.post("/api/masters/upload", headers=h, data=data,
                  files=[("files", (n, b, "application/octet-stream")) for n, b in files])


def by(report):
    return {t["slug"]: t for t in report["tables"]}


def test_a_check_saves_nothing(h):
    r = ok(send(h, [("MASTER DATA & TABLES.xlsx", master_data())]))
    t = by(r)
    assert r["dry_run"] and set(t) == {"brand", "sku", "customer", "employee"}
    assert (t["customer"]["added"], t["sku"]["added"], t["brand"]["added"],
            t["employee"]["added"]) == (2, 2, 2, 2)
    assert [x["slug"] for x in r["tables"]].index("brand") < \
        [x["slug"] for x in r["tables"]].index("sku")                      # parents first
    assert ok(c.get("/api/masters/customer", headers=h))["total"] == 0


def test_the_workbook_goes_in_as_it_is(h):
    r = ok(send(h, [("MASTER DATA & TABLES.xlsx", master_data())], dry=False))
    t = by(r)
    assert all(x["skipped"] == 0 for x in r["tables"]), r
    assert any("PASSWORD" in i for i in t["employee"]["ignored"])
    cust = ok(c.get("/api/masters/customer", params={"q": "ICON"}, headers=h))["rows"][0]
    assert cust["id"] == 3 and cust["aliases"] == ["ICONPHARMA", "ICON MEDICINE DISTRIBUTORS"]
    one = ok(c.get("/api/masters/customer", params={"q": "HEALTH"}, headers=h))["rows"][0]
    assert one["zone_id"] is None                                          # 0 = none
    p = ok(c.get("/api/masters/sku", params={"q": "CREMALAX TAB 6 S"}, headers=h))["rows"][0]
    assert p["id"] == 6 and p["product_brand_id__label"] == "12 — CREMALAX" and p["nrv"] == 181.4
    assert p["sap_product_id"] == "1040000141" and p["material_code"] is None
    e = ok(c.get("/api/masters/employee", params={"q": "SANTOSH"}, headers=h))["rows"][0]
    assert e["reporting_manager_id__label"] == "28865 — SANDEEP TEMKAR" and e["employee_code"] == "500004"
    # PASSWORD is not a column of the table at all
    from app import models_master as X
    assert "PASSWORD" not in {col.name for col in X.EmployeeMaster.__table__.columns}


def test_a_second_upload_updates_rather_than_adds(h):
    r = ok(send(h, [("MASTER DATA & TABLES.xlsx", master_data())], dry=False))
    assert all(x["added"] == 0 and x["unchanged"] == x["rows"] for x in r["tables"]), r
    assert ok(c.get("/api/masters/customer", headers=h))["total"] == 2


def test_the_old_system_tables_name_the_parents(h):
    """PRODUCT_MASTER_GROUP 8 arrives after the brands: their PRODUCT_GROUP_ID 8 now names it."""
    r = ok(send(h, [("old.xlsx", wb_bytes({
        "PRODUCT_MASTER_GROUP": [["PRODUCT_GROUP_ID", "PRODUCT_GROUP_NAME", "STATUS"], [8, "GASTRO", 1]],
        "ZONE": [["ZONE_ID", "ZONE_NAME"], [5, "EAST"]],
        "HQ_MASTER": [["HQ_ID", "HQ_NAME", "ZONE_ID"], [12, "KATHMANDU", 5]],
    }))], dry=False))
    t = by(r)
    assert (t["product_group"]["added"], t["zone"]["added"], t["headquarter"]["added"]) == (1, 1, 1)
    hq = ok(c.get("/api/masters/headquarter", params={"q": "KATHMANDU"}, headers=h))["rows"][0]
    assert hq["legacy_id"] == 12 and hq["code"] == "KATHMANDU" and hq["zone_id__label"].endswith("EAST")
    b = ok(c.get("/api/masters/brand", params={"q": "DIGENE"}, headers=h))["rows"][0]
    assert b["product_group_id__label"].endswith("GASTRO")


def test_a_bad_row_is_named_and_the_rest_go_in(h):
    r = ok(send(h, [("BRANDS.xlsx", wb_bytes({"Sheet1": [
        ["PRODUCT_BRAND_ID", "PRODUCT_BRAND_NAME", "NO_OF_SKU"],
        [50, "GOOD ONE", 1], [51, None, 1], [52, "BAD NUMBER", "many"]]}))],
        dry=False, slug="brand"))
    t = r["tables"][0]
    assert (t["added"], t["skipped"]) == (1, 2)
    assert any("Row 3" in e and "empty" in e for e in t["errors"])
    assert any("Row 4" in e and "whole number" in e for e in t["errors"])


def test_only_the_columns_sent_are_changed(h):
    ok(send(h, [("x.xlsx", wb_bytes({"PRODUCT_MASTER_BRAND": [
        ["PRODUCT_BRAND_ID", "NO_OF_SKU"], [9, 7]]}))], dry=False))
    b = ok(c.get("/api/masters/brand", params={"q": "DIGENE"}, headers=h))["rows"][0]
    assert b["no_of_sku"] == 7 and b["reporting"] == "P2"


def test_an_unknown_sheet_is_left_alone(h):
    r = send(h, [("random.xlsx", wb_bytes({"Whatever": [["A", "B"], [1, 2]]}))])
    assert r.status_code == 422 and "named after a master" in r.json()["detail"]


def test_export_is_the_workbook_and_reads_back_in(h):
    res = c.get("/api/masters/customer/export", headers=h)
    assert res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    ws = wb["CUSTOMER_MASTER"]
    head = [x.value for x in ws[1]]
    assert head[:3] == ["CUSTOMER_ID", "CUSTOMER_NAME", "CUSTOMER_SAP_ID"] and len(head) == 64
    assert head[11] == "CUSTOMER_ALIAS_1" and head[-1] == "STATUS"
    r = ok(send(h, [("CUSTOMER_MASTER.xlsx", res.content)]))
    assert r["tables"][0]["unchanged"] == r["tables"][0]["rows"]
    every = c.get("/api/masters/export-all", headers=h)
    names = openpyxl.load_workbook(io.BytesIO(every.content)).sheetnames
    assert {"CUSTOMER_MASTER", "EMPLOYEE_MASTER", "PRODUCT_MASTER_BRAND", "PRODUCT_MASTER",
            "Zones"} <= set(names)
    r = ok(send(h, [("MASTER_DATA.xlsx", every.content)]))
    assert all(x["skipped"] == 0 and x["added"] == 0 for x in r["tables"]), \
        [(x["slug"], x["errors"][:2]) for x in r["tables"] if x["skipped"] or x["added"]]
