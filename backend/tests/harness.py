import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("APP_PASSWORD", "test-password")
os.environ.setdefault("SECRET_KEY", "test-key")
os.environ.setdefault("STAGING_DIR", "/tmp/ds-staging")

from fastapi.testclient import TestClient            # noqa: E402
from sqlalchemy import create_engine                 # noqa: E402
from sqlalchemy.orm import sessionmaker              # noqa: E402
from sqlalchemy.pool import StaticPool               # noqa: E402

from app import database                             # noqa: E402
from app.main import app                             # noqa: E402

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
database.Base.metadata.create_all(engine)
Testing = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_db():
    db = Testing()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[database.get_db] = override_db

# the same seeding the real database gets at startup
from app.services import seed as _seed                # noqa: E402
_s = Testing()
_seed.ensure(_s)
_seed.ensure_masters(_s)
_seed.ensure_dist_ids(_s)
_s.close()
from app.services import triggers as _triggers        # noqa: E402
assert _triggers.ensure(engine), _triggers.READY      # sales_row -> MAPPING_MASTER(_MID)
client = TestClient(app)
anon = TestClient(app)


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content and code != 204 else None


def sign_in():
    return ok(client.post("/api/login", json={"password": "test-password", "who": "tester"}))["token"]


# ------------------------------------------------- converting with the masters
def make_known(detail: dict) -> None:
    """Put into the masters whatever a refused conversion named: each new
    customer and product (in a test group with a test territory and team), and
    the assignments missing. What a person would do on the master screens."""
    from sqlalchemy import func, select
    from app import models_master as X
    db = Testing()
    try:
        g = db.execute(select(X.ProductGroup).where(X.ProductGroup.code == "TST")).scalars().first()
        if g is None:
            country = db.execute(select(X.Country)).scalars().first()
            z = X.Zone(code="TSTZ", name="TEST ZONE", country_id=country.id, legacy_id=9901)
            db.add(z); db.flush()
            hq = X.Headquarter(code="TSTH", name="TEST HQ", zone_id=z.id, legacy_id=9901)
            db.add(hq); db.flush()
            db.add(X.Territory(code="TSTT", name="TEST TERRITORY", headquarter_id=hq.id, legacy_id=9901))
            g = X.ProductGroup(code="TST", name="TEST GROUP", legacy_id=9901)
            db.add(g)
            db.add(X.Team(code="TSTM", name="TEST TEAM", legacy_id=9901))
            db.add(X.ProductMasterBrand(product_brand_name="TEST BRAND", product_group_id=9901,
                                        reporting="X-OTHERS"))
            db.flush()
        brand = db.execute(select(X.ProductMasterBrand)
                           .where(X.ProductMasterBrand.product_brand_name == "TEST BRAND")).scalars().first()
        for e in detail.get("new_products", []):
            db.add(X.ProductMaster(sap_product_name=e["name"][:250], product_brand_id=brand.id))
        for e in detail.get("new_customers", []):
            db.add(X.CustomerMaster(customer_name=e["name"][:200]))
        db.flush()
        pairs = {(e["customer_id"], e["product_group_id"]) for e in detail.get("customers_not_assigned", [])}
        if detail.get("new_customers"):   # the customers just made, in the test group
            names = [e["name"][:200] for e in detail["new_customers"]]
            for cid in db.execute(select(X.CustomerMaster.id)
                                  .where(X.CustomerMaster.customer_name.in_(names))).scalars():
                pairs.add((cid, 9901))
        for cid, gid in pairs:
            db.add(X.CustomerTerrAssignment(customer_id=cid, territory_id=9901, hq_id=9901,
                                            product_group_id=gid, team_id=9901))
        db.commit()
        del func
    finally:
        db.close()


def commit_ok(token: str, headers: dict, body: dict) -> dict:
    """Convert; when it is refused for names not in the masters, add them as a
    person would and convert again. Returns the conversion's result."""
    for _ in range(3):
        r = client.post(f"/api/uploads/{token}/commit", headers=headers, json=body)
        if r.status_code == 409 and isinstance(r.json().get("detail"), dict):
            make_known(r.json()["detail"])
            continue
        return ok(r)
    raise AssertionError(r.text)
