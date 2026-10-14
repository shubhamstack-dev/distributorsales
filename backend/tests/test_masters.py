"""Master data: structure, alignment, currency, and the rules between them."""
import pytest
from sqlalchemy import create_engine, inspect, text

from tests.harness import client as c, ok, sign_in


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


def add(h, slug, **body):
    return ok(c.post(f"/api/masters/{slug}", json=body, headers=h), 201)


def refused(r, code, words):
    assert r.status_code == code, (r.status_code, r.text)
    assert words.lower() in r.json()["detail"].lower(), r.json()["detail"]


def rows(h, slug, **params):
    return ok(c.get(f"/api/masters/{slug}", params=params, headers=h))


@pytest.fixture(scope="module")
def world(h):
    """A small but complete company: one of everything, wired together."""
    w = {}
    w["y26"] = add(h, "year", year_number=2026)
    w["cls"] = add(h, "customer_classification", description="NON INSTITUTIONAL")
    w["rep"] = add(h, "reporting", reporting="P1")
    np_ = [x for x in rows(h, "country")["rows"] if x["code"] == "NP"][0]
    w["np"] = np_
    w["co"] = add(h, "company", code="acme", name="Acme Pharma")
    w["zone"] = add(h, "zone", code="Z-E", name="East", country_id=np_["id"])
    w["hq"] = add(h, "headquarter", code="KTM", name="Kathmandu", zone_id=w["zone"]["id"])
    w["hq2"] = add(h, "headquarter", code="PKR", name="Pokhara", zone_id=w["zone"]["id"])
    w["terr"] = add(h, "territory", code="KTM-1", name="Kathmandu 1", headquarter_id=w["hq"]["id"])
    w["terr2"] = add(h, "territory", code="PKR-1", name="Pokhara 1", headquarter_id=w["hq2"]["id"])
    w["pg"] = add(h, "product_group", code="CARD", name="Cardio", company_id=w["co"]["id"])
    w["pg2"] = add(h, "product_group", code="GAST", name="Gastro")
    # brands and products point at a group's Master ID, as the Excel tables do
    w["team"] = add(h, "team", code="T-CV", name="Cardio team")
    w["br"] = add(h, "brand", product_brand_name="ATORVA", product_group_id=w["pg"]["legacy_id"],
                  team_id=w["team"]["legacy_id"], reporting="P1")
    w["br2"] = add(h, "brand", product_brand_name="PANTO", product_group_id=w["pg2"]["legacy_id"])
    w["sku1"] = add(h, "sku", sap_product_name="ATORVA 10", product_brand_id=w["br"]["id"],
                    aliases="ATORVA-10 TAB\nATOR 10")
    w["sku2"] = add(h, "sku", sap_product_name="ATORVA 20", product_brand_id=w["br"]["id"])
    w["sku3"] = add(h, "sku", sap_product_name="PANTO 40", product_brand_id=w["br2"]["id"])
    w["des"] = add(h, "designation", code="MR", name="Medical Rep", level=1)
    w["des2"] = add(h, "designation", code="ABM", name="Area Manager", level=2)
    w["role"] = add(h, "role", code="FIELD", name="Field")
    w["cust"] = add(h, "customer", customer_name="CITY CHEMIST", cust_classification_id=w["cls"]["id"],
                    hq_id=w["hq"]["legacy_id"], aliases=["CITY CHEM KTM", "City Chemist"])
    w["boss"] = add(h, "employee", employee_ft_nm="Asha", designation_id=w["des2"]["legacy_id"])
    w["emp"] = add(h, "employee", employee_ft_nm="Bikash", designation_id=w["des"]["legacy_id"],
                   team="Cardio team", role_id=w["role"]["legacy_id"],
                   reporting_manager_id=w["boss"]["id"])
    w["tph"] = add(h, "team_pg_hq", team_id=w["team"]["legacy_id"],
                   product_group_id=w["pg"]["legacy_id"], hq_id=w["hq"]["legacy_id"])
    return w


# ================================================================== basics
def test_every_master_is_described(h):
    slugs = {m["slug"] for m in ok(c.get("/api/masters/meta", headers=h))}
    assert {"year", "distributor", "company", "country", "currency_rate", "company_country",
            "zone", "headquarter", "territory", "product_group", "brand", "sku", "reporting",
            "customer", "customer_classification", "designation", "role", "team", "employee",
            "team_pg_hq",
            "customer_terr_assignment", "customer_pg_assignment", "employee_terr_assignment",
            "employee_pg_assignment"} <= slugs
    assert not {"customer_assignment", "employee_assignment", "product_reporting",
                "product_reporting_sku", "team_product_group", "team_headquarter"} & slugs  # removed


def test_labels_come_back_with_references(h, world):
    t = rows(h, "territory", q="KTM-1")["rows"][0]
    assert t["headquarter_id__label"].endswith("KTM — Kathmandu")


def test_the_alias_pages_are_gone_and_aliases_live_on_the_row(h, world):
    slugs = {m["slug"] for m in ok(c.get("/api/masters/meta", headers=h))}
    assert "customer_alias" not in slugs and "sku_alias" not in slugs
    assert world["cust"]["aliases"] == ["CITY CHEM KTM", "City Chemist"]
    assert world["sku1"]["aliases"] == ["ATORVA-10 TAB", "ATOR 10"]
    # an alias is found by the search
    assert rows(h, "sku", q="ATOR 10")["total"] == 1
    # and kept in its own column, as in the workbook
    from tests.harness import Testing
    from app import models_master as X
    s = Testing()
    o = s.get(X.ProductMaster, world["sku1"]["id"])
    assert (o.alias_1, o.alias_2, o.alias_3) == ("ATORVA-10 TAB", "ATOR 10", None)
    s.close()


def test_too_many_aliases_are_refused(h):
    refused(c.post("/api/masters/customer", json={"customer_name": "X",
                   "aliases": [f"A{i}" for i in range(51)]}, headers=h), 422, "At most 50")


def test_master_ids_are_given_and_keyed_references_label(h, world):
    assert world["zone"]["legacy_id"] is not None
    assert world["hq"]["legacy_id"] != world["hq2"]["legacy_id"]
    b = rows(h, "brand", q="ATORVA")["rows"][0]
    assert b["product_group_id__label"].endswith("CARD — Cardio")
    s = rows(h, "sku", q="PANTO")["rows"][0]
    assert s["product_group_id"] == world["pg2"]["legacy_id"]        # taken from the brand
    opts = ok(c.get("/api/masters/product_group/options", params={"key": "legacy_id"}, headers=h))
    assert world["pg"]["legacy_id"] in [o["id"] for o in opts]


def test_the_row_id_is_kept_and_cannot_be_changed(h):
    x = add(h, "customer", id=777001, customer_name="ID KEPT")
    assert x["id"] == 777001
    y = ok(c.put("/api/masters/customer/777001", json={"id": 5, "customer_name": "ID KEPT 2"},
                 headers=h))
    assert y["id"] == 777001 and y["customer_name"] == "ID KEPT 2"
    refused(c.post("/api/masters/customer", json={"id": 777001, "customer_name": "Z"}, headers=h),
            409, "already taken")


def test_codes_are_upper_case_and_unique_regardless_of_case(h, world):
    assert world["co"]["code"] == "ACME"
    refused(c.post("/api/masters/company", json={"code": "Acme", "name": "Other"}, headers=h),
            409, "already has that code")


def test_required_fields_are_required(h):
    refused(c.post("/api/masters/zone", json={"code": "X"}, headers=h), 422, "name is required")


def test_a_reference_that_does_not_exist_is_refused(h, world):
    refused(c.post("/api/masters/headquarter", json={"code": "B", "name": "B", "zone_id": 99999},
                   headers=h), 422, "no longer exists")


def test_an_excel_table_id_may_point_ahead_of_its_parent(h):
    """CUSTOMER_MASTER.ZONE_ID 12 before ZONE 12 is uploaded: kept, and labelled so."""
    x = add(h, "customer", customer_name="AHEAD", zone_id=424242)
    assert x["zone_id"] == 424242 and "not in Zone" in x["zone_id__label"]


def test_something_in_use_cannot_be_deleted(h, world):
    refused(c.delete(f"/api/masters/zone/{world['zone']['id']}", headers=h), 409, "Head Quarter")
    # a product group named by a brand's PRODUCT_GROUP_ID is in use too
    refused(c.delete(f"/api/masters/product_group/{world['pg']['id']}", headers=h), 409, "Product Brand")
    refused(c.delete(f"/api/masters/brand/{world['br']['id']}", headers=h), 409, "SKU")


def test_delete_many_is_all_or_nothing(h, world):
    spare = add(h, "zone", code="Z-SP", name="Spare", country_id=world["np"]["id"])
    r = c.post("/api/masters/zone/delete-many", json={"ids": [spare["id"], world["zone"]["id"]]},
               headers=h)
    assert r.status_code == 409
    assert any(z["id"] == spare["id"] for z in rows(h, "zone")["rows"])      # still there
    ok(c.post("/api/masters/zone/delete-many", json={"ids": [spare["id"]]}, headers=h))


def test_inactive_rows_leave_the_drop_downs(h, world):
    x = add(h, "role", code="OLD", name="Old role", active=False)
    opts = ok(c.get("/api/masters/role/options", headers=h))
    assert x["id"] not in [o["id"] for o in opts]


# ================================================================ currency
def test_inr_and_npr_are_seeded_with_a_rate(h):
    r = ok(c.get("/api/currency/rate", params={"frm": "INR", "to": "NPR"}, headers=h))
    assert r["rate"] == 1.6 and r["via"] == "direct"


def test_the_other_direction_is_the_inverse(h):
    r = ok(c.get("/api/currency/convert",
                 params={"amount": 160, "frm": "NPR", "to": "INR", "on": "2026-09-01"}, headers=h))
    assert r["via"] == "inverse" and r["converted"] == 100.0


def test_a_later_rate_takes_over_from_its_date(h):
    add(h, "currency_rate", from_currency="INR", to_currency="NPR", rate=1.62,
        effective_from="2026-10-01")
    before = ok(c.get("/api/currency/rate", params={"on": "2026-09-30"}, headers=h))
    after = ok(c.get("/api/currency/rate", params={"on": "2026-10-01"}, headers=h))
    assert (before["rate"], after["rate"]) == (1.6, 1.62)


def test_a_pair_is_kept_in_one_direction_only(h):
    refused(c.post("/api/masters/currency_rate", json={"from_currency": "NPR", "to_currency": "INR",
                   "rate": 0.625, "effective_from": "2026-11-01"}, headers=h), 422, "INR → NPR")


def test_a_rate_needs_a_country_that_uses_the_currency(h):
    refused(c.post("/api/masters/currency_rate", json={"from_currency": "USD", "to_currency": "INR",
                   "rate": 83, "effective_from": "2026-01-01"}, headers=h), 422, "No country uses USD")


def test_no_rate_before_the_first_one(h):
    assert c.get("/api/currency/rate", params={"on": "1999-01-01"}, headers=h).status_code == 404


# =============================================================== structure
def test_company_country_pairs_are_unique(h, world):
    add(h, "company_country", company_id=world["co"]["id"], country_id=world["np"]["id"])
    refused(c.post("/api/masters/company_country", json={"company_id": world["co"]["id"],
                   "country_id": world["np"]["id"]}, headers=h), 409, "already assigned")


def test_sku_options_narrow_to_a_product_group(h, world):
    opts = ok(c.get("/api/masters/sku/options", params={"product_group_id": world["pg"]["id"]},
                    headers=h))
    assert sorted(o["label"].split(" — ")[1] for o in opts) == ["ATORVA 10", "ATORVA 20"]


def test_territories_narrow_to_a_zone(h, world):
    opts = ok(c.get("/api/masters/territory/options", params={"zone_id": world["zone"]["id"]},
                    headers=h))
    assert len(opts) == 2


def test_an_employee_cannot_report_in_a_circle(h, world):
    refused(c.put(f"/api/masters/employee/{world['boss']['id']}",
                  json={"reporting_manager_id": world["emp"]["id"]}, headers=h), 422, "circle")


# ================================================== the old system's tables
def test_a_year_is_a_year_once(h, world):
    refused(c.post("/api/masters/year", json={"year_number": 2026}, headers=h), 409, "already there")
    refused(c.post("/api/masters/year", json={"year_number": 26}, headers=h), 422, "between 2000")


def test_team_pg_hq_fills_its_names_and_is_kept_once(h, world):
    t = world["tph"]
    assert (t["team_name"], t["product_group_name"], t["hq_name"]) == ("Cardio team", "Cardio", "Kathmandu")
    refused(c.post("/api/masters/team_pg_hq", json={"team_id": world["team"]["legacy_id"],
                   "product_group_id": world["pg"]["legacy_id"], "hq_id": world["hq"]["legacy_id"]},
                   headers=h), 409, "already has")


def _view(h, slug, **params):
    meta = {m["slug"]: m for m in ok(c.get("/api/masters/meta", headers=h))}[slug]
    labels = [v["label"] for v in meta["view"]]
    return [dict(zip(labels, r["__view"])) for r in rows(h, slug, **params)["rows"]]


def test_lists_read_like_the_old_screens(h, world):
    t = [r for r in _view(h, "territory") if r["Territory Name"] == "Kathmandu 1"][0]
    assert (t["Zone"], t["HQ"], t["Active Status"]) == ("East", "Kathmandu", 1)
    s = [r for r in _view(h, "sku") if r["Product Name"] == "ATORVA 10"][0]
    # a SKU's group, team and reporting come through its brand
    assert (s["Product Group Name"], s["Product Brand Name"], s["Team"], s["Reporting"]) == \
        ("Cardio", "ATORVA", "Cardio team", "P1")
    cu = [r for r in _view(h, "customer") if r["Customer Name"] == "CITY CHEMIST"][0]
    assert cu["Customer Classification"] == "NON INSTITUTIONAL"
    e = [r for r in _view(h, "employee") if r["Employee Name"] == "Bikash"][0]
    assert (e["Role"], e["Designation"], e["Reporting Manager"]) == ("Field", "Medical Rep", "Asha")


def test_an_id_no_master_knows_shows_the_tables_own_name(h, world):
    add(h, "team_pg_hq", team_id=world["team"]["legacy_id"], product_group_id=world["pg"]["legacy_id"],
        hq_id=987, hq_name="DHANGADHI")
    r = [x for x in _view(h, "team_pg_hq") if x["HQ"] == "DHANGADHI"][0]
    assert (r["Team"], r["Product Group"]) == ("Cardio team", "Cardio")


def test_the_menu_follows_the_old_system(h):
    meta = ok(c.get("/api/masters/meta", headers=h))
    groups = list(dict.fromkeys(m["group"] for m in meta))
    assert groups == ["Organisation structure", "Product", "Master data", "Others",
                      "Assignment", "Assignment tables", "Budgeting", "Sales"]
    assert [m["title"] for m in meta if m["group"] == "Organisation structure"] == \
        ["Company", "Zone", "Head Quarter", "Territory"]


# ============================================================= distributor
def test_distributors_gain_master_details_and_keep_their_rules(h, world):
    d = add(h, "distributor", name="Himal Pharma", code="him", country_id=world["np"]["id"])
    rules = [x for x in ok(c.get("/api/distributors", headers=h)) if x["name"] == "Himal Pharma"][0]
    assert rules["cutoff_day"] == 15 and rules["invoice_mode"] == "seq"
    assert d["country_id__label"] == "NP — Nepal"
    refused(c.post("/api/masters/distributor", json={"name": "himal pharma"}, headers=h),
            409, "already exists")


def test_an_older_database_gets_the_new_distributor_columns():
    from app.services.migrate import ensure_columns
    eng = create_engine("sqlite://")
    with eng.begin() as cx:
        cx.execute(text("CREATE TABLE distributor (Id INTEGER PRIMARY KEY, Name VARCHAR(60))"))
    assert "column distributor.CountryId added" in ensure_columns(eng)
    assert ensure_columns(eng) == []                              # and only once
    cols = {x["name"] for x in inspect(eng).get_columns("distributor")}
    assert {"Code", "CountryId", "ContactPerson", "Phone", "Email", "MidCutoffDay",
            "SalesSheet", "ReturnSheet", "ProductKeepDot"} <= cols
