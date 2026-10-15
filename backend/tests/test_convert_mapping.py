"""Convert: names checked against the masters first, sales_row emptied before
each conversion, and every row copied by the triggers into MAPPING_MASTER, and
a Mid Month Y row into MAPPING_MASTER_MID as well, with the customer's
territory for the product's group."""
import io
import zipfile

import pytest
from sqlalchemy import func, select

from tests.harness import Testing, client as c, ok, sign_in   # first: the test database
from tests.test_yetichem import AHC                            # 2 customers x 2 products
from app import models as M                                     # noqa: E402
from app import models_master as X                              # noqa: E402

ZIP = io.BytesIO()
with zipfile.ZipFile(ZIP, "w") as z:
    z.writestr("MID-MONTH/AHCPW.xls", AHC)
ZIP = ZIP.getvalue()


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


@pytest.fixture(scope="module")
def yeti(h):
    return [d for d in ok(c.get("/api/distributors", headers=h)) if d["name"] == "Yetichem"][0]


def upload(h, yeti):
    r = ok(c.post("/api/uploads/inspect", headers=h, data={"distributor_id": str(yeti["id"])},
                  files=[("files", ("SALES.zip", ZIP, "application/zip"))]))
    return r["token"]


def convert(h, yeti, token, as_of):
    return c.post(f"/api/uploads/{token}/commit", headers=h, json={
        "distributor_id": yeti["id"], "as_of": as_of, "files": ["AHCPW.xls"]})


def count(model, **where):
    db = Testing()
    try:
        sel = select(func.count()).select_from(model)
        for k, v in where.items():
            sel = sel.where(getattr(model, k) == v)
        return db.execute(sel).scalar()
    finally:
        db.close()


def mapping_rows(model):
    db = Testing()
    try:
        return db.execute(select(model).where(model.dist_name == "Yetichem")).scalars().all()
    finally:
        db.close()


def add(*objs):
    db = Testing()
    try:
        for o in objs:
            db.add(o)
            db.flush()
        db.commit()
    finally:
        db.close()


def test_new_names_stop_the_conversion_and_say_which(h, yeti):
    token = upload(h, yeti)
    r = convert(h, yeti, token, "2026-10-20")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["message"].startswith("Nothing was converted.")
    assert [e["name"] for e in d["new_customers"]] == ["Om Medicals", "Rantoks Pharma Pvt ltd"]
    assert [e["name"] for e in d["new_products"]] == ["PAN 40 TAB", "STEMETIL 5MG TAB"]
    assert d["new_products"][0]["files"] == ["AHCPW.xls"]
    assert count(M.SalesRow) == 0 and count(X.MidSalesMapping, dist_name="Yetichem") == 0
    # the upload is kept: once the masters are right it converts without sending it again
    assert convert(h, yeti, token, "2026-10-20").status_code == 409


def test_names_match_by_alias_and_then_the_assignment_is_asked_for(h, yeti):
    country = Testing().execute(select(X.Country)).scalars().first()
    z = X.Zone(code="ZY", name="ZONE Y", country_id=country.id, legacy_id=501)
    add(z)
    hq = X.Headquarter(code="HKT", name="KATHMANDU", zone_id=z.id, legacy_id=501)
    add(hq)
    add(X.Territory(code="TKT", name="KATHMANDU T", headquarter_id=hq.id, legacy_id=502),
        X.ProductGroup(code="PCR", name="PRIMARY CARE", legacy_id=503),
        X.Team(code="TPC", name="PC TEAM", legacy_id=504),
        X.ProductMasterBrand(id=601, product_brand_name="STEMETIL", product_group_id=503,
                             reporting="P1"))
    # by name with the punctuation ignored, and by an alias
    add(X.ProductMaster(id=701, sap_product_name="PAN 40 TAB", product_brand_id=601),
        X.ProductMaster(id=702, sap_product_name="STEMETIL 5 MG TABLET", product_brand_id=601,
                        alias_1="Stemetil 5mg Tab."),
        X.CustomerMaster(id=801, customer_name="RANTOKS PHARMA PVT LTD"),
        X.CustomerMaster(id=802, customer_name="OM MEDICAL STORE", alias_3="OM MEDICALS"),
        X.CustomerTerrAssignment(customer_id=801, territory_id=502, hq_id=501,
                                 product_group_id=503, team_id=504))
    r = convert(h, yeti, upload(h, yeti), "2026-10-20")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["new_customers"] == [] and d["new_products"] == []
    assert [(e["customer"], e["product_group"]) for e in d["customers_not_assigned"]] == \
        [("Om Medicals", "PRIMARY CARE")]
    assert "assign them on Customer Terr-PG" in d["message"]


def test_a_mid_month_row_goes_into_both_tables_with_the_assignment(h, yeti):
    add(X.CustomerTerrAssignment(customer_id=802, territory_id=502, hq_id=501,
                                 product_group_id=503, team_id=504))
    b = ok(convert(h, yeti, upload(h, yeti), "2026-10-20"))         # after the 15th: Mid Month Y
    assert (b["mid_month"], b["mapping_tables"]) == ("Y", ["MAPPING_MASTER", "MAPPING_MASTER_MID"])
    assert b["mapping_replaced"] == {"MAPPING_MASTER": 0, "MAPPING_MASTER_MID": 0}
    rows = mapping_rows(X.MidSalesMapping)
    assert len(rows) == b["rows"] == count(M.SalesRow)
    assert count(X.SalesMapping, dist_name="Yetichem") == b["rows"]       # and MAPPING_MASTER
    stem = [r for r in rows if r.product_id == 702][0]
    assert (stem.dist_id, stem.month, stem.year) == (16212104, "October", 2026)
    assert (stem.hq_id, stem.hq_name, stem.territory_id, stem.territory_name) == \
        (501, "KATHMANDU", 502, "KATHMANDU T")
    assert (stem.product_group_id, stem.product_group_name, stem.product_brand_name,
            stem.product_brand_category) == (503, "PRIMARY CARE", "STEMETIL", "P1")
    assert (stem.product_name, stem.product_master_name) == ("STEMETIL 5MG TAB", "STEMETIL 5 MG TABLET")
    assert (stem.customer_id, stem.customer_master_name) == (801, "RANTOKS PHARMA PVT LTD")
    assert (stem.sales_qty, stem.sales_value, stem.return_quantity) == (40, 4000, 0)
    om = [r for r in rows if r.customer_id == 802]
    assert om and all(r.customer_master_name == "OM MEDICAL STORE" for r in om)


def test_converting_again_replaces_and_sales_row_holds_only_the_last(h, yeti):
    before = count(X.MidSalesMapping, dist_name="Yetichem")
    b = ok(convert(h, yeti, upload(h, yeti), "2026-10-21"))
    assert b["mapping_replaced"] == {"MAPPING_MASTER": before, "MAPPING_MASTER_MID": before}
    assert count(X.MidSalesMapping, dist_name="Yetichem") == before        # not twice
    assert count(X.SalesMapping, dist_name="Yetichem") == before
    assert count(M.SalesRow) == b["rows"]
    assert count(M.SalesRow, batch_id=b["batch_id"]) == b["rows"]          # the last batch only


def test_the_month_that_ended_goes_to_mapping_master_only(h, yeti):
    mid = count(X.MidSalesMapping, dist_name="Yetichem")
    b = ok(convert(h, yeti, upload(h, yeti), "2026-11-05"))          # on/before the 15th: October, N
    assert (b["mid_month"], b["month"], b["mapping_tables"]) == ("N", "October", ["MAPPING_MASTER"])
    # the full month replaces October's mid-month rows in MAPPING_MASTER ...
    assert b["mapping_replaced"] == {"MAPPING_MASTER": mid}
    rows = mapping_rows(X.SalesMapping)
    assert len(rows) == b["rows"] and all(r.hq_name == "KATHMANDU" for r in rows)
    # ... and MAPPING_MASTER_MID keeps them
    assert count(X.MidSalesMapping, dist_name="Yetichem") == mid


def test_an_old_batch_says_its_rows_were_replaced(h, yeti):
    first = ok(c.get("/api/batches", headers=h))[-1]
    d = ok(c.get(f"/api/batches/{first['id']}", headers=h))
    assert d.get("rows_replaced") is True
    r = c.get(f"/api/batches/{first['id']}/export", headers=h)
    assert r.status_code == 410 and "MAPPING_MASTER" in r.json()["detail"]


# ------------------------------------------------------------- Data Error
def test_data_error_compares_temp_with_main(h, yeti):
    r = ok(c.get(f"/api/data-error?distributor_id={yeti['id']}&file_type=invoice", headers=h))
    # the last conversion: October, Mid Month N, 3 rows, all in MAPPING_MASTER
    assert (r["month"], r["year"], r["table"]) == ("October", 2026, "MAPPING_MASTER")
    assert (r["temp"], r["main"], r["not_inserted"], r["incomplete"], r["duplicates"]) == (3, 3, 0, 0, 0)
    assert r["amount"] == 2500                                   # 4000 - 2000 + 500
    assert (r["currency"], r["amount_inr"]) == ("NPR", 1562.5)    # at the seeded 1.6 INR/NPR
    m = ok(c.get(f"/api/data-error?distributor_id={yeti['id']}&file_type=mid", headers=h))
    # the last mid-month conversion's rows are no longer in sales_row; MID still has them
    assert (m["table"], m["temp"], m["main"], m["not_inserted"]) == ("MAPPING_MASTER_MID", 0, 3, 0)


def test_data_error_counts_repeats_and_rows_without_an_hq(h, yeti):
    db = Testing()
    try:
        r = db.execute(select(X.SalesMapping).where(X.SalesMapping.dist_name == "Yetichem")).scalars().first()
        cols = {k: getattr(r, k) for k in r.__mapper__.attrs.keys() if k != "id"}
        db.add(X.SalesMapping(**cols))                           # the same row again
        db.add(X.SalesMapping(**{**cols, "invoice_no": "X-1", "hq_id": None}))
        db.commit()
    finally:
        db.close()
    d = ok(c.get(f"/api/data-error?distributor_id={yeti['id']}&file_type=invoice", headers=h))
    assert (d["main"], d["duplicates"], d["incomplete"]) == (5, 1, 1)
    assert len(d["duplicate_rows"]) == 2 and d["incomplete_rows"][0]["invoice_no"] == "X-1"
    assert c.get("/api/data-error?distributor_id=1&file_type=stock", headers=h).status_code == 422
