"""HEAD_COUNT: filled from the workbook, edited on screen, never added or deleted there."""
import io

import openpyxl
import pytest

from tests.harness import client as c, ok, sign_in   # first: it points the app at a test database


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


def book(rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "HEAD_COUNT"
    ws.append(["DIVISION", "HQ", "COUNT"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(h, data):
    r = ok(c.post("/api/masters/upload", headers=h, data={"dry_run": "false"},
                  files=[("files", ("Book1.xlsx", data, "application/octet-stream"))]))
    return r["tables"][0]


ROWS = [["GASTRO ", "BIRATNAGAR", 1], ["GASTRO ", "KATHMANDU", 2], ["GASTRO ", "TOTAL", 3]]


def rows(h):
    return {(r["division"], r["hq"]): r for r in ok(c.get("/api/masters/head_count", headers=h))["rows"]}


def test_the_sheet_fills_the_table_and_reads_the_same_twice(h):
    t = upload(h, book(ROWS))
    assert (t["master"], t["added"], t["skipped"]) == ("Head Count", 3, 0)
    assert rows(h)[("GASTRO", "TOTAL")]["count"] == 3            # "GASTRO " read as GASTRO
    t = upload(h, book(ROWS))
    assert (t["added"], t["unchanged"]) == (0, 3)
    t = upload(h, book([["GASTRO", "KATHMANDU", 4]]))            # same row, new count
    assert (t["added"], t["updated"]) == (0, 1)


def test_only_the_count_is_edited(h):
    r = rows(h)[("GASTRO", "BIRATNAGAR")]
    ok(c.put(f"/api/masters/head_count/{r['id']}", headers=h,
             json={"count": 5, "division": "WH", "hq": "POKHRA"}))
    after = rows(h)
    assert after[("GASTRO", "BIRATNAGAR")]["count"] == 5 and ("WH", "POKHRA") not in after
    r2 = c.put(f"/api/masters/head_count/{r['id']}", headers=h, json={"count": -1})
    assert r2.status_code == 422 and "0 or more" in r2.json()["detail"]


def test_rows_are_not_added_or_deleted_on_screen(h):
    assert c.post("/api/masters/head_count", headers=h,
                  json={"division": "WH", "hq": "POKHRA", "count": 1}).status_code == 405
    rid = next(iter(rows(h).values()))["id"]
    assert c.delete(f"/api/masters/head_count/{rid}", headers=h).status_code == 405
    assert c.post("/api/masters/head_count/delete-many", headers=h, json={"ids": [rid]}).status_code == 405
    assert len(rows(h)) == 3
    meta = {m["slug"]: m for m in ok(c.get("/api/masters/meta", headers=h))}["head_count"]
    assert (meta["group"], meta["can_add"], meta["can_delete"]) == ("Budgeting", False, False)
