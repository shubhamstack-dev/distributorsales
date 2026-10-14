"""Create / delete / assign all / clean on the three assignment pages."""
import pytest

from tests.harness import client as c, ok, sign_in   # first: it points the app at a test database


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


def add(h, slug, **body):
    return ok(c.post(f"/api/masters/{slug}", json=body, headers=h), 201)


def run(h, kind, action, code=200, **body):
    r = c.post(f"/api/assign/{kind}/{action}", json=body, headers=h)
    assert r.status_code == code, r.text
    return r.json()


def total(h, path):
    return ok(c.get(path, headers=h))["total"]


@pytest.fixture(scope="module")
def w(h):
    np_ = [x for x in ok(c.get("/api/masters/country", headers=h))["rows"] if x["code"] == "NP"][0]
    z = add(h, "zone", legacy_id=71, code="ZA", name="ZONE A", country_id=np_["id"])
    h1 = add(h, "headquarter", legacy_id=71, code="BTW", name="BUTWAL", zone_id=z["id"])
    h2 = add(h, "headquarter", legacy_id=72, code="BRG", name="BIRGUNJ", zone_id=z["id"])
    add(h, "territory", legacy_id=71, code="T-BTW", name="BUTWAL", headquarter_id=h1["id"])
    add(h, "territory", legacy_id=72, code="T-BRG", name="BIRGUNJ", headquarter_id=h2["id"])
    add(h, "product_group", legacy_id=71, code="GAS", name="GASTRO")
    add(h, "product_group", legacy_id=72, code="PCR", name="PRIMARY CARE")
    add(h, "team", legacy_id=71, code="TG", name="GASTRO TEAM")
    b1 = add(h, "brand", id=7101, product_brand_name="CREON", product_group_id=71)
    b2 = add(h, "brand", id=7102, product_brand_name="DIGENE", product_group_id=72)
    for pid, b in ((7201, b1), (7202, b1), (7203, b2)):
        add(h, "sku", id=pid, sap_product_name=f"SKU {pid}", product_brand_id=b["id"])
    add(h, "customer", id=7301, customer_name="HEALTH MEDECINE DISTRIBUTOR")
    add(h, "customer", id=7302, customer_name="A ONE PHARMACEUTICALS")
    add(h, "employee", id=7401, employee_ft_nm="SANTOSH", employee_lt_nm="PANDEY")
    return {}


# ------------------------------------------------------------- Team PG HQ
def test_team_pg_hq_checks_then_creates_with_names(h, w):
    body = dict(team_ids=[71], hq_ids=[71, 72], product_group_ids=[71])
    assert run(h, "team_pg_hq", "create", dry_run=True, **body)["rows_added"] == 2
    assert total(h, "/api/masters/team_pg_hq?team_id=71") == 0          # a check writes nothing
    assert run(h, "team_pg_hq", "create", **body)["rows_added"] == 2
    assert run(h, "team_pg_hq", "create", **body)["rows_added"] == 0    # never twice
    rows = ok(c.get("/api/masters/team_pg_hq?team_id=71", headers=h))["rows"]
    assert {(r["team_name"], r["hq_name"]) for r in rows} == {("GASTRO TEAM", "BUTWAL"),
                                                              ("GASTRO TEAM", "BIRGUNJ")}
    run(h, "team_pg_hq", "create", 422, team_ids=[71], hq_ids=[999], product_group_ids=[71])


# --------------------------------------------------------------- customer
def test_customer_create_takes_the_team_from_team_pg_hq(h, w):
    body = dict(customer_ids=[7301], territory_ids=[71], product_group_ids=[71])
    r = run(h, "customer", "create", dry_run=True, **body)
    assert (r["territory_rows_added"], r["product_rows_added"]) == (1, 2)
    assert total(h, "/api/terr-pg/customer?customer_id=7301") == 0
    run(h, "customer", "create", **body)
    rows = ok(c.get("/api/terr-pg/customer?customer_id=7301", headers=h))["rows"]
    assert [r[:5] for r in rows] == [["HEALTH MEDECINE DISTRIBUTOR", "BUTWAL", "BUTWAL", "GASTRO",
                                      "GASTRO TEAM"]] * 2
    assert run(h, "customer", "create", **body)["product_rows_added"] == 0


def test_a_group_no_team_carries_is_left_out_and_said(h, w):
    r = run(h, "customer", "create", dry_run=True, customer_ids=[7301], territory_ids=[71],
            product_group_ids=[72])
    assert r["territory_rows_added"] == 0 and r["product_rows_added"] == 0
    assert "No team has product group 72 in HQ 71" in r["notes"][0]


def test_customer_delete_takes_the_groups_products_with_it(h, w):
    body = dict(customer_ids=[7301], territory_ids=[71], product_group_ids=[71])
    r = run(h, "customer", "delete", dry_run=True, **body)
    assert (r["territory_rows_removed"], r["product_rows_removed"]) == (1, 2)
    assert total(h, "/api/terr-pg/customer?customer_id=7301") == 2       # checked, not done
    run(h, "customer", "delete", **body)
    assert total(h, "/api/terr-pg/customer?customer_id=7301") == 0


def test_assign_all_gives_every_customer_every_hq_and_product_then_clean(h, w):
    r = run(h, "customer", "assign_all", customer_ids=[7301, 7302])
    # Team PG HQ has GASTRO in both HQs: one territory row each; three active SKUs
    assert (r["territory_rows_added"], r["product_rows_added"]) == (4, 6)
    assert run(h, "customer", "assign_all", customer_ids=[7301, 7302])["product_rows_added"] == 0
    r = run(h, "customer", "clean", customer_ids=[7302])
    assert (r["territory_rows_removed"], r["product_rows_removed"]) == (2, 3)
    assert total(h, "/api/terr-pg/customer?customer_id=7301") > 0       # the other one kept


# --------------------------------------------------------------- employee
def test_employee_hq_and_one_or_many_groups(h, w):
    r = run(h, "employee", "create", employee_ids=[7401], hq_ids=[72], product_group_ids=[71, 72])
    assert (r["territory_rows_added"], r["product_rows_added"]) == (1, 3)
    rows = ok(c.get("/api/terr-pg/employee?employee_id=7401", headers=h))["rows"]
    assert {(x[0], x[1], x[3]) for x in rows} == {("SANTOSH PANDEY", "BIRGUNJ", "GASTRO"),
                                                  ("SANTOSH PANDEY", "BIRGUNJ", "PRIMARY CARE")}
    # one group out; the HQ stays
    r = run(h, "employee", "delete", employee_ids=[7401], product_group_ids=[71])
    assert (r["territory_rows_removed"], r["product_rows_removed"]) == (0, 2)
    assert total(h, "/api/terr-pg/employee?employee_id=7401") == 1
    run(h, "employee", "create", 422, employee_ids=[7401])              # nothing chosen
    r = run(h, "employee", "clean", employee_ids=[7401])
    assert (r["territory_rows_removed"], r["product_rows_removed"]) == (1, 1)


def test_unknown_page_or_action(h, w):
    assert c.post("/api/assign/nobody/create", json={}, headers=h).status_code == 404
    run(h, "employee", "assign_all", 422)
    run(h, "customer", "explode", 422)
