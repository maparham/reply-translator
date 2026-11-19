import uuid
from datetime import datetime, timezone

import pytest

from translator import history, styles
from helpers import PREV, body


def test_generate_then_tweak_updates_same_item(user_client, fake_gen):
    hid = user_client.post("/api/generate", json=body()).json()["history_id"]
    fake_gen.data = {**fake_gen.data, "message": "kurz"}
    hid2 = user_client.post("/api/tweak", json=body(tweak="shorter", history_id=hid, previous=PREV)).json()["history_id"]
    items = user_client.get("/api/history").json()
    assert hid2 == hid and len(items) == 1 and items[0]["output"]["message"] == "kurz"


def test_dont_save(user_client):
    assert user_client.post("/api/generate", json=body(save=False)).json()["history_id"] is None
    assert user_client.get("/api/history").json() == []


def test_anon_has_no_history(anon_client):
    assert anon_client.get("/api/history").status_code == 401
    assert anon_client.post("/api/generate", json=body()).json()["history_id"] is None


def test_item_shape_and_timestamps(user_client, fake_gen):
    fake_gen.data = {"received_gist": "g", "message": "m", "back_translation": "b"}
    user_client.post("/api/generate", json=body(received="hi"))
    item = user_client.get("/api/history").json()[0]
    assert set(item) == {"id", "created_at", "updated_at", "style_label", "language_code", "inputs", "output"}
    assert item["inputs"] == {"text": "say no", "received": "hi", "my_language": "English"}
    assert item["created_at"].endswith("Z") and len(item["created_at"]) == 20


def test_list_newest_updated_first(conn):
    t = lambda m: datetime(2026, 11, 19, 10, m, tzinfo=timezone.utc)
    a = history.save(conn, "u", None, "L", "de-AT", {}, {}, now=t(0))
    b = history.save(conn, "u", None, "L", "de-AT", {}, {}, now=t(1))
    assert [i["id"] for i in history.list_items(conn, "u")] == [b, a]
    history.save(conn, "u", a, "L", "de-AT", {}, {"message": "x"}, now=t(2))
    assert [i["id"] for i in history.list_items(conn, "u")] == [a, b]


def test_tweak_with_foreign_history_id_saves_new_item(client_factory, user_client):
    hid = user_client.post("/api/generate", json=body()).json()["history_id"]
    other = client_factory()
    assert other.post("/api/login/clerk", json={"token": "user2"}).status_code == 200
    hid2 = other.post("/api/tweak", json=body(tweak="shorter", history_id=hid, previous=PREV)).json()["history_id"]
    assert hid2 and hid2 != hid
    assert [i["id"] for i in other.get("/api/history").json()] == [hid2]
    assert user_client.get("/api/history").json()[0]["output"]["message"] != "Hallo lang"


def test_import_idempotent(user_client):
    items = [{"id": str(uuid.uuid4()), "created_at": "2026-11-19T10:00:00Z", "style_label": "Official",
              "language_code": "de-AT", "inputs": {"text": "a"}, "output": {"message": "b"}}]
    assert user_client.post("/api/history/import", json={"items": items}).json() == {"imported": 1}
    assert user_client.post("/api/history/import", json={"items": items}).json() == {"imported": 0}
    assert len(user_client.get("/api/history").json()) == 1


def test_import_skips_invalid(user_client):
    bad = [{"id": "not-a-uuid", "inputs": {}, "output": {}},
           {"id": str(uuid.uuid4()), "created_at": "2026-11-19T10:00:00Z", "updated_at": "2026-11-19T10:00:00Z", "style_label": "x",
            "language_code": "de-AT", "inputs": {"text": "a" * 8001, "received": "", "my_language": "English"},
            "output": {"received_gist": "", "message": "b", "back_translation": "c"}},
           {"id": str(uuid.uuid4()), "inputs": {"text": 5}, "output": {}}, "junk"]
    assert user_client.post("/api/history/import", json={"items": bad}).json() == {"imported": 0}


def test_import_limits(user_client):
    r = user_client.post("/api/history/import", json={"items": [{}] * 201})
    assert r.status_code == 400 and r.json() == {"error": "Too many items"}
    assert user_client.post("/api/history/import", json={"items": "x"}).status_code == 400


def test_cannot_touch_others_items(conn):
    i = history.save(conn, "user_a", None, "Official", "de-AT", {}, {"message": "x"})
    with pytest.raises(PermissionError):
        history.save(conn, "user_b", i, "Official", "de-AT", {}, {"message": "y"})
    assert history.delete(conn, "user_b", i) is False
    assert history.import_items(conn, "user_b", [{"id": i, "output": {}, "inputs": {}}]) == 0
    assert history.list_items(conn, "user_a")[0]["output"] == {"message": "x"}


def test_delete_one_and_404(client_factory, user_client):
    hid = user_client.post("/api/generate", json=body()).json()["history_id"]
    other = client_factory()
    other.post("/api/login/clerk", json={"token": "user2"})
    assert other.delete(f"/api/history/{hid}").status_code == 404
    assert user_client.delete(f"/api/history/{hid}").status_code == 200
    r = user_client.delete(f"/api/history/{hid}")
    assert r.status_code == 404 and r.json() == {"error": "Not found"}


def test_delete_all(user_client):
    user_client.post("/api/generate", json=body())
    user_client.delete("/api/history")
    assert user_client.get("/api/history").json() == []


def test_deleted_style_history_still_lists(user_client, conn):
    user_client.post("/api/generate", json=body())
    styles.delete_style(conn, 1)
    assert user_client.get("/api/history").json()[0]["style_label"] == "Official"


def _max_item():
    big = "ü" * history.MAX_TEXT
    return {"id": str(uuid.uuid4()), "created_at": "2026-11-19T10:00:00Z", "style_label": "x" * 100, "language_code": "de-AT",
            "inputs": {"text": big, "received": big, "my_language": big},
            "output": {"received_gist": big, "message": big, "back_translation": big}}


IMPORT_BATCH = 2  # must equal IMPORT_BATCH in static/app.js (3 max-size items exceed 256 KB; 25 did too)


def test_max_size_import_batch_fits_body_limit(user_client):
    import json
    items = [_max_item() for _ in range(IMPORT_BATCH)]
    raw = json.dumps({"items": items}, ensure_ascii=False).encode()  # raw UTF-8, as browsers send
    r = user_client.post("/api/history/import", content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and r.json() == {"imported": IMPORT_BATCH}
