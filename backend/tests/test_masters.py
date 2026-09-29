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
    w["y26"] = add(h, "year", year_value=2026, label="FY 2026-27", start_date="2026-04-01",
                   end_date="2027-03-31", is_current=True)
    w["y27"] = add(h, "year", year_value=2027, label="FY 2027-28", start_date="2027-04-01",
                   end_date="2028-03-31")
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
    w["br"] = add(h, "brand", code="ATOR", name="Atorva", product_group_id=w["pg"]["id"])
    w["br2"] = add(h, "brand", code="PANT", name="Panto", product_group_id=w["pg2"]["id"])
    w["sku1"] = add(h, "sku", code="ATOR10", name="Atorva 10", brand_id=w["br"]["id"])
    w["sku2"] = add(h, "sku", code="ATOR20", name="Atorva 20", brand_id=w["br"]["id"])
    w["sku3"] = add(h, "sku", code="PANT40", name="Panto 40", brand_id=w["br2"]["id"])
    w["team"] = add(h, "team", code="T-CV", name="Cardio team")
    w["des"] = add(h, "designation", code="MR", name="Medical Rep", level=1)
    w["des2"] = add(h, "designation", code="ABM", name="Area Manager", level=2)
    w["role"] = add(h, "role", code="FIELD", name="Field")
    w["cust"] = add(h, "customer", code="c-001", name="City Chemist", classification="Chemist",
                    country_id=np_["id"])
    w["boss"] = add(h, "employee", code="E1", name="Asha", designation_id=w["des2"]["id"])
    w["emp"] = add(h, "employee", code="E2", name="Bikash", designation_id=w["des"]["id"],
                   team_id=w["team"]["id"], role_id=w["role"]["id"],
                   headquarter_id=w["hq"]["id"], reports_to_id=w["boss"]["id"])
    add(h, "team_product_group", year_id=w["y26"]["id"], team_id=w["team"]["id"],
        product_group_id=w["pg"]["id"])
    add(h, "team_headquarter", year_id=w["y26"]["id"], team_id=w["team"]["id"],
        headquarter_id=w["hq"]["id"])
    return w


# ================================================================== basics
def test_every_master_is_described(h):
    slugs = {m["slug"] for m in ok(c.get("/api/masters/meta", headers=h))}
    assert {"year", "distributor", "company", "country", "currency_rate", "company_country",
            "zone", "headquarter", "territory", "product_group", "brand", "sku",
            "product_reporting", "product_reporting_sku", "customer", "designation", "role",
            "team", "team_product_group", "team_headquarter", "employee",
            "customer_assignment", "employee_assignment"} <= slugs


def test_labels_come_back_with_references(h, world):
    t = rows(h, "territory", q="KTM-1")["rows"][0]
    assert t["headquarter_id__label"] == "KTM — Kathmandu"


def test_codes_are_upper_case_and_unique_regardless_of_case(h, world):
    assert world["co"]["code"] == "ACME"
    refused(c.post("/api/masters/company", json={"code": "Acme", "name": "Other"}, headers=h),
            409, "already has that code")


def test_required_fields_are_required(h):
    refused(c.post("/api/masters/zone", json={"code": "X"}, headers=h), 422, "name is required")


def test_a_reference_that_does_not_exist_is_refused(h):
    refused(c.post("/api/masters/brand", json={"code": "B", "name": "B", "product_group_id": 99999},
                   headers=h), 422, "no longer exists")


def test_something_in_use_cannot_be_deleted(h, world):
    refused(c.delete(f"/api/masters/zone/{world['zone']['id']}", headers=h), 409, "Headquarters")


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


# =================================================================== years
def test_only_one_year_is_current(h, world):
    ok(c.put(f"/api/masters/year/{world['y27']['id']}", json={"is_current": True}, headers=h))
    cur = [y for y in rows(h, "year")["rows"] if y["is_current"]]
    assert [y["year_value"] for y in cur] == [2027]
    ok(c.put(f"/api/masters/year/{world['y26']['id']}", json={"is_current": True}, headers=h))


def test_a_year_must_end_after_it_starts(h):
    refused(c.post("/api/masters/year", json={"year_value": 2030, "label": "x",
                   "start_date": "2030-04-01", "end_date": "2030-03-01"}, headers=h),
            422, "end after")


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
    assert sorted(o["label"].split(" ")[0] for o in opts) == ["ATOR10", "ATOR20"]


def test_territories_narrow_to_a_zone(h, world):
    opts = ok(c.get("/api/masters/territory/options", params={"zone_id": world["zone"]["id"]},
                    headers=h))
    assert len(opts) == 2


def test_reporting_lines_carry_a_flag_and_one_line_per_sku_per_year(h, world):
    refused(c.post("/api/masters/product_reporting", json={"year_id": world["y26"]["id"],
                   "code": "BAD", "name": "x", "flag": "P3"}, headers=h), 422, "P1, P2")
    p1 = add(h, "product_reporting", year_id=world["y26"]["id"], code="ATORVA", name="Atorva",
             flag="P1")
    x = add(h, "product_reporting", year_id=world["y26"]["id"], code="OTH", name="Others",
            flag="X")
    m = add(h, "product_reporting_sku", product_reporting_id=p1["id"], sku_id=world["sku1"]["id"])
    assert m["year_id"] == world["y26"]["id"]                   # taken from the line
    refused(c.post("/api/masters/product_reporting_sku",
                   json={"product_reporting_id": x["id"], "sku_id": world["sku1"]["id"]},
                   headers=h), 409, "another line")


def test_an_employee_cannot_report_in_a_circle(h, world):
    refused(c.put(f"/api/masters/employee/{world['boss']['id']}",
                  json={"reports_to_id": world["emp"]["id"]}, headers=h), 422, "circle")


# =============================================================== alignment
def _ca(world, **over):
    return {"year_id": world["y26"]["id"], "customer_id": world["cust"]["id"],
            "territory_id": world["terr"]["id"], "team_id": world["team"]["id"],
            "product_group_id": world["pg"]["id"], "sku_id": world["sku1"]["id"], **over}


def test_customer_sku_must_be_in_the_group(h, world):
    refused(c.post("/api/masters/customer_assignment",
                   json=_ca(world, sku_id=world["sku3"]["id"]), headers=h), 422, "not in the product group")


def test_customer_team_must_carry_the_group(h, world):
    refused(c.post("/api/masters/customer_assignment",
                   json=_ca(world, product_group_id=world["pg2"]["id"], sku_id=world["sku3"]["id"]),
                   headers=h), 422, "does not carry")


def test_customer_team_must_cover_the_territory_hq(h, world):
    refused(c.post("/api/masters/customer_assignment",
                   json=_ca(world, territory_id=world["terr2"]["id"]), headers=h), 422, "Pokhara")


def test_customer_alignment_in_bulk_by_product_group(h, world):
    body = {k: v for k, v in _ca(world).items() if k != "sku_id"}
    r = ok(c.post("/api/masters/customer_assignment/bulk", json=body, headers=h))
    assert r == {"created": 2, "skipped": 0, "skus": 2}
    r = ok(c.post("/api/masters/customer_assignment/bulk", json=body, headers=h))
    assert r == {"created": 0, "skipped": 2, "skus": 2}           # nothing twice
    got = rows(h, "customer_assignment", customer_id=world["cust"]["id"])
    assert got["total"] == 2 and got["rows"][0]["sku_id__label"].startswith("ATOR")


def test_employee_alignment_in_bulk(h, world):
    body = {"year_id": world["y26"]["id"], "employee_id": world["emp"]["id"],
            "territory_id": world["terr"]["id"], "product_group_id": world["pg"]["id"],
            "brand_id": world["br"]["id"]}
    assert ok(c.post("/api/masters/employee_assignment/bulk", json=body, headers=h))["created"] == 2
    # the employee's team does not carry Gastro
    refused(c.post("/api/masters/employee_assignment/bulk",
                   json={**body, "product_group_id": world["pg2"]["id"], "brand_id": None},
                   headers=h), 422, "does not carry")


def test_a_year_can_start_from_the_one_before(h, world):
    y26, y27 = world["y26"]["id"], world["y27"]["id"]
    for slug in ("team_product_group", "team_headquarter"):
        r = ok(c.post(f"/api/masters/{slug}/copy-year",
                      json={"from_year_id": y26, "to_year_id": y27}, headers=h))
        assert r["created"] == 1
    r = ok(c.post("/api/masters/customer_assignment/copy-year",
                  json={"from_year_id": y26, "to_year_id": y27}, headers=h))
    assert r["created"] == 2 and r["skipped"] == 0
    r = ok(c.post("/api/masters/product_reporting/copy-year",
                  json={"from_year_id": y26, "to_year_id": y27}, headers=h))
    assert r["created"] == 2
    assert rows(h, "product_reporting_sku", year_id=y27)["total"] == 1


def test_a_closed_year_cannot_be_changed(h, world):
    y = add(h, "year", year_value=2020, label="FY 2020-21", start_date="2020-04-01",
            end_date="2021-03-31", active=False)
    refused(c.post("/api/masters/team_product_group", json={"year_id": y["id"],
                   "team_id": world["team"]["id"], "product_group_id": world["pg"]["id"]},
                   headers=h), 422, "closed")


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
    assert "distributor.CountryId" in ensure_columns(eng)
    assert ensure_columns(eng) == []                              # and only once
    cols = {x["name"] for x in inspect(eng).get_columns("distributor")}
    assert {"Code", "CountryId", "ContactPerson", "Phone", "Email"} <= cols
