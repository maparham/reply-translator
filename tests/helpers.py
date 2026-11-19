def body(**kw) -> dict:
    return {"style_id": 1, "language_code": "de-AT", "my_language": "English", "text": "say no",
            "received": None, "save": True, "history_id": None} | kw


PREV = {"received_gist": "", "message": "Hallo lang", "back_translation": "Hello long"}
