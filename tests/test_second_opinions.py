"""Second opinions: a reader asks other radiologists to read the same study. It stays on the asker's
worklist; each of them finds it under Second opinions and saves a report of their own, and everyone on
the study can read every report. Own scope (the local and AWS runtimes), on the fixture providers."""
import os

import pytest
from fastapi.testclient import TestClient

from core.api import create_app
from core.providers.fixture import BLOB, FixtureDatastore, FixtureTable
from core.providers.local import DevAuth, FileBlob, TemplateLLM

R1, R2, R3 = ("radiologist-1@dev.auralane.local", "radiologist-2@dev.auralane.local",
              "radiologist-3@dev.auralane.local")


@pytest.fixture
def app():
    auth = DevAuth(secret=os.urandom(32).hex(), password=os.urandom(8).hex())
    table = FixtureTable()
    for row in table.scan("worklist"):                  # R1's worklist: every fixture study
        row["assigned_to"], row["assigned_name"] = R1, "Reader 1"
        table.put_item("worklist", row)
    p = {"runtime": "fixture", "blob": FileBlob(BLOB, url_base="/api/blob"), "datastore": FixtureDatastore(table),
         "table": table, "auth": auth, "llm": TemplateLLM(), "worklist_scope": "own"}
    client = TestClient(create_app(p))
    client.h = lambda user: {"Authorization": f"Bearer {auth.issue(user)}"}
    client.p = p
    client.chest = next(r["study"] for r in table.scan("worklist") if r["modality"] == "CR")
    return client


def ask(app, study, readers, note="", who="radiologist-1"):
    return app.post(f"/api/studies/{study}/opinions", json={"readers": readers, "note": note}, headers=app.h(who))


def test_a_study_asked_about_stays_with_its_reader_and_opens_for_the_ones_asked(app):
    s = app.chest
    r = ask(app, s, [R2, R3], "the left base looks different to me")
    assert r.status_code == 200, r.text
    assert [o["to"] for o in r.json()["opinions"]] == [R2, R3]
    assert all(o["status"] == "waiting" and o["requested_by"] == R1 for o in r.json()["opinions"])

    # It is still on R1's worklist, and not on the worklists of the two asked.
    assert s in [x["study"] for x in app.get("/api/worklist", headers=app.h("radiologist-1")).json()["studies"]]
    assert app.get("/api/worklist", headers=app.h("radiologist-2")).json()["studies"] == []
    # ...but they can open it, and its images, and read what they were asked.
    d = app.get(f"/api/studies/{s}", headers=app.h("radiologist-2"))
    assert d.status_code == 200
    assert d.json()["my_opinion"]["note"] == "the left base looks different to me"
    assert d.json()["can_request_opinion"] is False
    series = d.json()["series"][0]["series_uid"]
    assert app.get(f"/api/studies/{s}/series/{series}", headers=app.h("radiologist-2")).status_code == 200
    # Someone who was not asked still cannot.
    assert app.get(f"/api/studies/{s}", headers=app.h("radiologist-4")).status_code == 403


def test_the_asker_sees_who_it_went_to_and_the_ones_asked_are_told_it_is_waiting(app):
    s = app.chest
    ask(app, s, [R2])
    ask(app, s, [R3])                                         # a later request adds to the list
    d = app.get(f"/api/studies/{s}", headers=app.h("radiologist-1")).json()
    assert [o["to"] for o in d["opinions"]] == [R2, R3] and d["can_request_opinion"] is True
    assert app.get("/api/worklist", headers=app.h("radiologist-2")).json()["opinions_waiting"] == 1
    assert app.get("/api/worklist", headers=app.h("radiologist-1")).json()["opinions_waiting"] == 0
    # The list rows say it too.
    row = next(x for x in app.get("/api/worklist", headers=app.h("radiologist-1")).json()["studies"] if x["study"] == s)
    assert [o["to"] for o in row["opinions"]] == [R2, R3]


def test_opening_marks_the_request_seen_and_is_audited(app):
    s = app.chest
    ask(app, s, [R2])
    app.get(f"/api/studies/{s}", headers=app.h("radiologist-2"))
    d = app.get(f"/api/studies/{s}", headers=app.h("radiologist-1")).json()
    assert d["opinions"][0]["status"] == "opened" and d["opinions"][0]["opened_at"]
    assert app.get("/api/worklist", headers=app.h("radiologist-2")).json()["opinions_waiting"] == 0
    actions = [e["action"] for e in app.p["table"].query("audit", study=s)]
    assert "opinion_requested" in actions and "opinion_open" in actions


def test_each_radiologist_writes_a_report_of_their_own_and_everyone_on_the_study_can_read_them(app):
    s = app.chest
    ask(app, s, [R2, R3])
    a = app.post(f"/api/studies/{s}/draft", json={"text": "reader one's text", "reviewed": True}, headers=app.h("radiologist-1"))
    b = app.post(f"/api/studies/{s}/draft", json={"text": "reader two's text", "reviewed": False}, headers=app.h("radiologist-2"))
    assert a.json()["report"]["author"] == R1 and b.json()["report"]["author"] == R2
    assert b.json()["report"]["version"] == "000002"          # one numbering per study, whoever wrote it

    d1 = app.get(f"/api/studies/{s}", headers=app.h("radiologist-1")).json()
    d2 = app.get(f"/api/studies/{s}", headers=app.h("radiologist-2")).json()
    # The editor opens with your own report, not somebody else's.
    assert d1["report"]["text"] == "reader one's text" and d2["report"]["text"] == "reader two's text"
    # All reports on the study are there for the dropdown, yours first.
    assert [(r["author"], r["mine"]) for r in d1["reports"]] == [(R1, True), (R2, False)]
    assert [(r["author"], r["mine"]) for r in d2["reports"]] == [(R2, True), (R1, False)]
    assert {o["to"]: o["status"] for o in d1["opinions"]} == {R2: "draft", R3: "waiting"}
    # The asker's own edit stays on the row; the one asked does not overwrite it.
    assert d1["draft_review"]["text"] == "reader one's text" and d2["draft_review"] is None
    # Each may open the other's saved version; a radiologist outside the study may not.
    assert app.get(f"/api/reports/{s}/000001", headers=app.h("radiologist-2")).json()["report"]["text"] == "reader one's text"
    assert app.get(f"/api/reports/{s}/000002", headers=app.h("radiologist-1")).status_code == 200
    assert app.get(f"/api/reports/{s}/000001", headers=app.h("radiologist-4")).status_code == 403
    # A second-opinion report is in the author's own Reports, and the audit says what it was.
    assert [r["study"] for r in app.get("/api/reports", headers=app.h("radiologist-2")).json()["reports"]] == [s]
    saved = [e for e in app.p["table"].query("audit", study=s) if e["action"] == "draft_saved"]
    assert saved and saved[0]["detail"].get("second_opinion") is True


def test_the_one_asked_can_report_before_the_studys_reader_has_written_anything(app):
    s = app.chest
    ask(app, s, [R2])
    r = app.post(f"/api/studies/{s}/draft", json={"text": "first, and from the second reader", "reviewed": True},
                 headers=app.h("radiologist-2"))
    assert r.status_code == 200, r.text
    assert r.json()["report"]["author"] == R2 and r.json()["draft_review"]["by"] == R2
    # The reader's own study was not touched: no edit of theirs is on the row.
    d = app.get(f"/api/studies/{s}", headers=app.h("radiologist-1")).json()
    assert d["draft_review"] is None and d["report"] is None
    assert [(x["author"], x["mine"]) for x in d["reports"]] == [(R2, False)]


def test_only_the_reader_of_a_study_can_ask_and_not_for_the_wrong_people(app):
    s = app.chest
    assert ask(app, s, [R2], who="radiologist-4").status_code == 403       # not theirs
    assert ask(app, s, [R1]).status_code == 409                            # not yourself
    assert ask(app, s, ["nobody@x.io"]).status_code == 400                 # not a radiologist
    assert ask(app, s, []).status_code == 422                              # someone is needed
    assert ask(app, s, [R2]).status_code == 200
    assert ask(app, s, [R2]).status_code == 409                            # not twice
    # A radiologist asked cannot pass it on, and cannot give the verdict on someone else's lane.
    assert ask(app, s, [R3], who="radiologist-2").status_code == 403
    assert app.post(f"/api/studies/{s}/verdict", json={"verdict": "agree"}, headers=app.h("radiologist-2")).status_code == 403
    # The same person twice in one request is asked once.
    other = next(r["study"] for r in app.p["table"].scan("worklist") if r["study"] != s)
    r = ask(app, other, [R3, R3])
    assert [o["to"] for o in r.json()["opinions"]] == [R3]


@pytest.mark.parametrize("lane", ["CRITICAL", "URGENT", "ABSTAIN", "EXPEDITED", "ROUTINE", "FAILED", "REPEAT"])
def test_a_study_in_any_lane_can_be_sent_like_mail_and_stays_where_it_is(app, lane):
    table = app.p["table"]
    row = next(r for r in table.scan("worklist") if r["modality"] == "CR")
    row["lane"] = lane                                        # whatever lane it is in
    table.put_item("worklist", row)
    s = row["study"]
    r = ask(app, s, [R2, R3], "Please read this one when you can")
    assert r.status_code == 200, r.text
    # It is still on the sender's worklist, in the same lane, with the same reader.
    mine = {x["study"]: x for x in app.get("/api/worklist", headers=app.h("radiologist-1")).json()["studies"]}
    assert s in mine and mine[s]["lane"] == lane and mine[s]["assigned_to"] == R1
    assert table.get_item("worklist", {"study": s})["assigned_to"] == R1
    # And it is in the others' Second opinions, with the message.
    for who in ("radiologist-2", "radiologist-3"):
        got = app.get("/api/second-opinions", headers=app.h(who)).json()["received"]
        assert [(x["study"]["study"], x["opinion"]["note"]) for x in got] == [(s, "Please read this one when you can")]
        assert got[0]["study"]["assigned_to"] == R1


def test_the_old_hand_over_is_gone(app):
    s = app.chest
    assert app.post(f"/api/studies/{s}/second-read", json={"reader": R2}, headers=app.h("radiologist-1")).status_code in (404, 405)


def test_a_reader_who_does_not_read_the_pool_is_not_asked(app, monkeypatch):
    s = app.chest
    import core.assign as assign
    monkeypatch.setattr(assign, "directory", lambda auth, path=assign.READERS_FILE: [
        {"id": R1, "username": "radiologist-1", "name": "Reader 1", "pools": ["Chest", "Neuro"]},
        {"id": R2, "username": "radiologist-2", "name": "Reader 2", "pools": ["Neuro"]}])
    client = TestClient(create_app(app.p))
    r = client.post(f"/api/studies/{s}/opinions", json={"readers": [R2]}, headers=app.h("radiologist-1"))
    assert r.status_code == 409 and "does not read the Chest pool" in r.json()["detail"]


def test_the_second_opinions_lists_show_what_was_received_and_what_was_sent(app):
    s = app.chest
    ask(app, s, [R2, R3])
    other = next(r["study"] for r in app.p["table"].scan("worklist") if r["study"] != s)
    ask(app, other, [R2])
    got = app.get("/api/second-opinions", headers=app.h("radiologist-2")).json()
    assert {x["study"]["study"] for x in got["received"]} == {s, other} and got["sent"] == []
    assert all(x["opinion"]["status"] == "waiting" for x in got["received"])
    # A report moves that request to the bottom, marked reported.
    app.post(f"/api/studies/{s}/draft", json={"text": "done", "reviewed": True}, headers=app.h("radiologist-2"))
    got = app.get("/api/second-opinions", headers=app.h("radiologist-2")).json()
    assert [x["opinion"]["status"] for x in got["received"]] == ["waiting", "reported"]
    # The asker's list groups each study once, with everyone asked.
    sent = app.get("/api/second-opinions", headers=app.h("radiologist-1")).json()["sent"]
    assert {x["study"]["study"]: [o["to"] for o in x["opinions"]] for x in sent} == {s: [R2, R3], other: [R2]}
    assert app.get("/api/second-opinions", headers=app.h("radiologist-4")).json() == {
        "disclaimer": got["disclaimer"], "received": [], "sent": []}


def test_a_study_never_asked_about_looks_as_before(app):
    d = app.get(f"/api/studies/{app.chest}", headers=app.h("radiologist-1")).json()
    assert d["opinions"] == [] and d["reports"] == [] and d["my_opinion"] is None and d["report"] is None
