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
_s.close()
client = TestClient(app)
anon = TestClient(app)


def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.text)
    return r.json() if r.content and code != 204 else None


def sign_in():
    return ok(client.post("/api/login", json={"password": "test-password", "who": "tester"}))["token"]
