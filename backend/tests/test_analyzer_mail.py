"""Reports › Analyzer Email: after a conversion (or by hand) the month's actuals
are calculated, the Nepal Analyzer made, kept for download, and emailed with
the workbook attached. Sent to a small SMTP server of the tests' own."""
import io
import zipfile

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from tests.harness import Testing, client as c, make_known, ok, sign_in
from tests.fake_smtp import Server
from tests.test_yetichem import AHC
from app import models_master as X
from app import models_report as R
from app.services import mailer

ZIP = io.BytesIO()
with zipfile.ZipFile(ZIP, "w") as z:
    z.writestr("SALES/AHCPW.xls", AHC)
ZIP = ZIP.getvalue()


@pytest.fixture(scope="module")
def h():
    return {"Authorization": f"Bearer {sign_in()}"}


@pytest.fixture(scope="module")
def smtp():
    s = Server()
    yield s
    s.close()


def configure(h, smtp, **more):
    return ok(c.put("/api/reports/mail-settings", headers=h, json={
        "smtp_host": "127.0.0.1", "smtp_port": smtp.port, "security": "none", "auth": "password",
        "username": smtp.user, "password": smtp.password, "from_address": smtp.user,
        "from_name": "Distributor Sales", **more}))


def year(y):
    db = Testing()
    try:
        if not db.execute(select(X.YearMaster).where(X.YearMaster.year_number == y)).first():
            db.add(X.YearMaster(year_number=y, active=1))
            db.commit()
    finally:
        db.close()


def test_settings_start_with_the_address_and_keep_the_password_secret(h, smtp):
    s = ok(c.get("/api/reports/mail-settings", headers=h))
    assert s["recipients"] == "181296shubham@gmail.com"
    assert s["auto_on_convert"] and s["calculate_first"] and s["download_after"]
    assert s["mail_on_convert"] is False              # one mail a month, by Send Mail
    assert s["presets"]["m365"]["smtp_host"] == "smtp.office365.com"
    s = configure(h, smtp)
    assert s["password_set"] and s["password_readable"] and "password" not in s
    db = Testing()
    try:
        stored = db.get(R.ReportMailSettings, 1).password_enc
        assert stored and smtp.password not in stored                    # encrypted
    finally:
        db.close()
    # an empty password keeps the stored one
    s = ok(c.put("/api/reports/mail-settings", headers=h, json={"password": "", "from_name": "DS"}))
    assert s["password_set"] and s["from_name"] == "DS"
    assert c.put("/api/reports/mail-settings", headers=h, json={"recipients": "not-an-address"}).status_code == 422
    assert c.put("/api/reports/mail-settings", headers=h, json={"subject": "{nope}"}).status_code == 422


def test_test_email(h, smtp):
    before = len(smtp.messages)
    r = ok(c.post("/api/reports/mail-settings/test", headers=h, json={"to": "someone@aequm.test"}))
    assert r["ok"] and len(smtp.messages) == before + 1
    assert smtp.messages[-1][1] == ["someone@aequm.test"]


def test_a_wrong_password_is_said_plainly(h, smtp):
    configure(h, smtp, password="wrong")
    r = c.post("/api/reports/mail-settings/test", headers=h, json={"to": "x@aequm.test"})
    assert r.status_code == 422 and "refused the sign-in" in r.json()["detail"]
    configure(h, smtp)


def test_by_hand_the_workbook_is_attached(h, smtp):
    before = len(smtp.messages)
    j = ok(c.post("/api/reports/analyzer-jobs", headers=h, json={
        "month": "September", "year": 2026, "calculate": False, "send": True,
        "recipients": "181296shubham@gmail.com, boss@aequm.test"}))
    j = ok(c.get(f"/api/reports/analyzer-jobs/{j['id']}", headers=h))         # the run went after the reply
    assert (j["status"], j["mail_status"], j["trigger"]) == ("done", "sent", "manual"), j
    assert j["file_name"] == "NepalAnalyzerReports_September2026.xlsx"
    sender, rcpt, msg = smtp.messages[before]
    assert rcpt == ["181296shubham@gmail.com", "boss@aequm.test"]
    assert msg["Subject"] == "Nepal Analyzer Report — September 2026"
    att = [p for p in msg.iter_attachments()]
    assert [a.get_filename() for a in att] == ["NepalAnalyzerReports_September2026.xlsx"]
    wb = load_workbook(io.BytesIO(att[0].get_content()))
    assert wb.sheetnames[0] == "NEPAL LEVEL" and len(wb.sheetnames) == 18
    html = msg.get_body(("html",)).get_content()
    assert "Distributors" in html and "September" in html
    f = c.get(f"/api/reports/analyzer-jobs/{j['id']}/file", headers=h)
    assert f.status_code == 200 and f.content == att[0].get_content()


def test_a_failed_email_keeps_the_workbook_and_can_be_sent_again(h, smtp):
    configure(h, smtp, password="wrong")
    j = ok(c.post("/api/reports/analyzer-jobs", headers=h, json={
        "month": "August", "year": 2026, "calculate": False, "send": True}))
    j = ok(c.get(f"/api/reports/analyzer-jobs/{j['id']}", headers=h))
    assert (j["status"], j["mail_status"], j["has_file"]) == ("failed", "failed", True)
    assert "refused the sign-in" in j["mail_detail"]
    configure(h, smtp)
    before = len(smtp.messages)
    ok(c.post(f"/api/reports/analyzer-jobs/{j['id']}/send", headers=h, json={}))
    j = ok(c.get(f"/api/reports/analyzer-jobs/{j['id']}", headers=h))
    assert (j["status"], j["mail_status"]) == ("done", "sent")
    assert smtp.messages[before][1] == ["181296shubham@gmail.com"]
    assert "Distributors" in smtp.messages[before][2].get_body(("html",)).get_content()   # the summary kept


def test_bad_addresses_are_refused_up_front(h):
    r = c.post("/api/reports/analyzer-jobs", headers=h, json={
        "month": "August", "year": 2026, "send": True, "recipients": "a@b.com, nope"})
    assert r.status_code == 422 and "'nope'" in r.json()["detail"]


def test_microsoft_365_oauth(h, smtp, monkeypatch):
    monkeypatch.setattr(mailer, "m365_token", lambda t, cl, s: smtp.token)
    configure(h, smtp, auth="m365_oauth", tenant_id="91a9940b", client_id="0399c057", client_secret="shh",
              password="")
    before = len(smtp.messages)
    ok(c.post("/api/reports/mail-settings/test", headers=h, json={"to": "x@aequm.test"}))
    assert smtp.logins[-1] == ("XOAUTH2", True) and len(smtp.messages) == before + 1
    s = ok(c.get("/api/reports/mail-settings", headers=h))
    assert s["client_secret_set"] and s["tenant_id"] == "91a9940b"
    configure(h, smtp, auth="password")


def test_convert_calculates_and_makes_but_does_not_mail(h, smtp):
    year(2026)
    yeti = [d for d in ok(c.get("/api/distributors", headers=h)) if d["name"] == "Yetichem"][0]

    def upload():
        return ok(c.post("/api/uploads/inspect", headers=h, data={"distributor_id": str(yeti["id"])},
                         files=[("files", ("SALES.zip", ZIP, "application/zip"))]))["token"]

    def convert(**more):
        token = upload()
        body = {"distributor_id": yeti["id"], "as_of": "2026-10-20", "files": ["AHCPW.xls"], **more}
        r = c.post(f"/api/uploads/{token}/commit", headers=h, json=body)
        if r.status_code == 409:                               # names the masters lack: as a person would
            make_known(r.json()["detail"])
            r = c.post(f"/api/uploads/{token}/commit", headers=h, json=body)
        return ok(r)

    before = len(smtp.messages)
    b = convert()
    j = b["analyzer_job"]
    assert j and j["trigger"] == "convert" and j["batch_id"] == b["batch_id"] and j["calculate"] and not j["send"]
    j = ok(c.get(f"/api/reports/analyzer-jobs/{j['id']}", headers=h))
    assert (j["status"], j["mail_status"], j["has_file"]) == ("done", None, True), j
    assert any("actuals worked out" in line for line in j["log"])
    assert j["month"] == b["month"] == "October" and j["distributor"] == "Yetichem"
    assert len(smtp.messages) == before                        # no mail after a conversion
    listed = ok(c.get(f"/api/reports/analyzer-jobs?batch_id={b['batch_id']}", headers=h))
    assert [x["id"] for x in listed] == [j["id"]]

    # ticked on Convert for once: it mails
    b = convert(analyzer={"enabled": True, "calculate": True, "send": True})
    j = ok(c.get(f"/api/reports/analyzer-jobs/{b['analyzer_job']['id']}", headers=h))
    assert j["mail_status"] == "sent" and len(smtp.messages) == before + 1
    assert f"batch {b['batch_id']} (Yetichem)" in smtp.messages[-1][2].get_body(("plain",)).get_content()

    # unticked on Convert: no run
    assert convert(analyzer={"enabled": False})["analyzer_job"] is None

    # switched off on Analyzer Email: no run either, and the conversion is as before
    ok(c.put("/api/reports/mail-settings", headers=h, json={"auto_on_convert": False}))
    b = convert()
    assert b["analyzer_job"] is None and b["rows"] > 0
    ok(c.put("/api/reports/mail-settings", headers=h, json={"auto_on_convert": True}))


def test_send_mail_for_the_month_once_every_distributor_is_in(h, smtp):
    st = ok(c.get("/api/reports/month-status", headers=h))           # the latest batch's month
    assert (st["month"], st["year"]) == ("October", 2026)
    by = {d["name"]: d for d in st["distributors"]}
    assert set(by) >= {"Yetichem", "Pharmachem", "Gunjeshwari"}
    assert by["Yetichem"]["converted"] and by["Yetichem"]["rows"] > 0 and by["Yetichem"]["last_batch"]
    assert not by["Pharmachem"]["converted"] and by["Pharmachem"]["last_batch"] is None
    assert st["all_converted"] is False
    before = len(smtp.messages)
    j = ok(c.post("/api/reports/analyzer-jobs", headers=h, json={
        "month": "October", "year": 2026, "calculate": True, "send": True}))
    j = ok(c.get(f"/api/reports/analyzer-jobs/{j['id']}", headers=h))
    assert (j["status"], j["mail_status"]) == ("done", "sent") and len(smtp.messages) == before + 1
    st = ok(c.get("/api/reports/month-status?month=october&year=2026", headers=h))
    assert st["last_mail"]["id"] == j["id"] and st["last_mail"]["recipients"] == "181296shubham@gmail.com"
    other = ok(c.get("/api/reports/month-status?month=July&year=2026", headers=h))
    assert other["month"] == "July" and not any(d["converted"] for d in other["distributors"])
    assert c.get("/api/reports/month-status?month=Smarch&year=2026", headers=h).status_code == 400


def test_a_run_that_cannot_calculate_says_why(h, smtp):
    j = ok(c.post("/api/reports/analyzer-jobs", headers=h, json={
        "month": "March", "year": 2031, "calculate": True, "send": True}))
    j = ok(c.get(f"/api/reports/analyzer-jobs/{j['id']}", headers=h))
    assert j["status"] == "failed" and "2031 is not in Year" in j["error"] and j["mail_status"] == "not sent"
    assert c.get(f"/api/reports/analyzer-jobs/{j['id']}/file", headers=h).status_code == 404


def test_a_run_cut_short_by_a_restart_is_marked(h):
    from datetime import datetime
    from app.reports.analyzer_job import stop_unfinished
    db = Testing()
    try:
        j = R.ReportJob(created_at=datetime.now(), trigger="manual", month="May", year=2026, calculate=1, send=1,
                        recipients="181296shubham@gmail.com", status="running", step="Making the workbook")
        db.add(j)
        db.commit()
        assert stop_unfinished(db) >= 1
        db.refresh(j)
        assert j.status == "failed" and "restarted" in j.error and j.mail_status == "not sent"
    finally:
        db.close()
