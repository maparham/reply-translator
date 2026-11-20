import pytest

from translator import styles


def test_seed(conn):
    styles.seed(conn)
    styles.seed(conn)
    assert [s.label for s in styles.list_styles(conn, True)] == ["Official", "Friendly", "Neutral"]
    assert all(s.provider == "anthropic" and s.model == "claude-haiku-5-5" for s in styles.list_styles(conn, True))
    assert styles.list_languages(conn) == styles.SEED_LANGUAGES and styles.SEED_LANGUAGES[0]["code"] == "de-AT"


def test_seed_skips_when_data_exists(conn):
    styles.create_style(conn, "Mine", "", "p", "openai", "m")
    styles.seed(conn)
    assert [s.label for s in styles.list_styles(conn, False)] == ["Mine"]


def test_inactive_hidden(conn):
    s = styles.create_style(conn, "X", "", "p", "openai", "m", active=False)
    assert s.id not in [x.id for x in styles.list_styles(conn, True)]
    assert s.id in [x.id for x in styles.list_styles(conn, False)]


def test_reorder(conn):
    a = styles.create_style(conn, "A", "", "p", "openai", "m")
    b = styles.create_style(conn, "B", "", "p", "openai", "m")
    styles.reorder_styles(conn, [b.id, a.id])
    assert [s.label for s in styles.list_styles(conn, False)] == ["B", "A"]


def test_bad_provider(conn):
    with pytest.raises(ValueError):
        styles.create_style(conn, "A", "", "p", "gemini", "m")


@pytest.mark.parametrize("args", [("", "", "p", "openai", "m"), ("A", "", "", "openai", "m"), ("A", "", "p", "openai", " ")])
def test_empty_fields(conn, args):
    with pytest.raises(ValueError):
        styles.create_style(conn, *args)


def test_update_and_delete(conn):
    s = styles.create_style(conn, "A", "d", "p", "openai", "m")
    u = styles.update_style(conn, s.id, label="B", active=False, model="m2")
    assert (u.label, u.active, u.model, u.prompt) == ("B", False, "m2", "p")
    assert styles.update_style(conn, 999, label="Z") is None
    with pytest.raises(ValueError):
        styles.update_style(conn, s.id, provider="gemini")
    with pytest.raises(ValueError):
        styles.update_style(conn, s.id, label=" ")
    with pytest.raises(ValueError):
        styles.update_style(conn, s.id, bogus=1)
    assert styles.get_style(conn, s.id).label == "B"
    assert styles.delete_style(conn, s.id) is True
    assert styles.delete_style(conn, s.id) is False
    assert styles.get_style(conn, s.id) is None


def test_position_increments(conn):
    a = styles.create_style(conn, "A", "", "p", "openai", "m")
    b = styles.create_style(conn, "B", "", "p", "openai", "m")
    assert b.position == a.position + 1


def test_set_languages(conn):
    styles.seed(conn)
    styles.set_languages(conn, [{"code": "en", "name": "English"}, {"code": "de-AT", "name": "German (Austria)"}])
    assert [l["code"] for l in styles.list_languages(conn)] == ["en", "de-AT"]


def test_seed_prompts_clean(conn):
    styles.seed(conn)
    for s in styles.list_styles(conn, False):
        assert s.prompt.strip()
        assert "..." not in s.prompt and "[" not in s.prompt and "/" not in s.prompt


def test_seed_atomic(conn, monkeypatch):
    monkeypatch.setattr(styles, "_replace_languages", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        styles.seed(conn)
    assert styles.list_styles(conn, False) == []


@pytest.mark.parametrize("items", [
    [{"code": "", "name": "X"}], [{"code": "x", "name": " "}], [{"name": "X"}],
    [{"code": "a", "name": "A"}, {"code": "a", "name": "B"}],
])
def test_set_languages_invalid(conn, items):
    styles.set_languages(conn, [{"code": "en", "name": "English"}])
    with pytest.raises(ValueError):
        styles.set_languages(conn, items)
    assert styles.list_languages(conn) == [{"code": "en", "name": "English"}]


def test_update_empty_and_none_description(conn):
    s = styles.create_style(conn, "A", "d", "p", "openai", "m")
    for k in ("prompt", "model"):
        with pytest.raises(ValueError):
            styles.update_style(conn, s.id, **{k: ""})
    assert styles.update_style(conn, s.id, description=None).description == ""
