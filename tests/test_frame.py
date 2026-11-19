import pytest

from translator import frame


def test_compose_prompt_contains_parts():
    system, user = frame.build_prompt("Be formal.", "German (Austria)", "English", "say no")
    assert "Be formal." in system and "German (Austria)" in system and "English" in system
    assert "Style instructions" in system
    assert "<what_i_want_to_say>" in user and "say no" in user and "<received_message>" not in user


def test_reply_prompt_includes_received():
    _, user = frame.build_prompt("s", "German (Austria)", "English", "ok", received="Hallo")
    assert "<received_message>" in user and "Hallo" in user


def test_tweak_prompt():
    prev = frame.Output("", "Hallo", "Hello")
    _, user = frame.build_prompt("s", "de", "en", "x", previous=prev, tweak="shorter")
    assert "<previous_message>" in user and "Hallo" in user
    assert "<change_request>" in user and frame.TWEAKS["shorter"][1] in user


def test_unknown_tweak():
    with pytest.raises(ValueError):
        frame.build_prompt("s", "de", "en", "x", previous=frame.Output("", "a", "b"), tweak="louder")


def test_tweak_requires_previous_and_vice_versa():
    with pytest.raises(ValueError):
        frame.build_prompt("s", "de", "en", "x", tweak="shorter")
    with pytest.raises(ValueError):
        frame.build_prompt("s", "de", "en", "x", previous=frame.Output("", "a", "b"))


def test_parse_ok_and_errors():
    assert frame.parse_output({"received_gist": "", "message": " Hi ", "back_translation": "Hi"}, False).message == "Hi"
    for bad in [None, [], {"message": "x"}, {"received_gist": "", "message": " ", "back_translation": "b"},
                {"received_gist": "", "message": 3, "back_translation": "b"}]:
        with pytest.raises(frame.FrameError):
            frame.parse_output(bad, False)
    with pytest.raises(frame.FrameError):
        frame.parse_output({"received_gist": "", "message": "m", "back_translation": "b"}, True)


def test_tweak_ids():
    assert list(frame.TWEAKS) == ["shorter", "more_polite", "firmer", "less_formal"]
    assert [v[0] for v in frame.TWEAKS.values()] == ["Shorter", "More polite", "Firmer", "Less formal"]


def test_schema_strict_compatible():
    s = frame.OUTPUT_SCHEMA
    assert s["type"] == "object" and s["additionalProperties"] is False
    assert s["required"] == ["received_gist", "message", "back_translation"]
    assert set(s["properties"]) == set(s["required"])
    assert all(p["type"] == "string" and p["description"] for p in s["properties"].values())


def test_output_to_dict():
    assert frame.Output("a", "b", "c").to_dict() == {"received_gist": "a", "message": "b", "back_translation": "c"}


def test_my_languages():
    assert len(frame.MY_LANGUAGES) == len(set(frame.MY_LANGUAGES)) == 30
    assert "English" in frame.MY_LANGUAGES
