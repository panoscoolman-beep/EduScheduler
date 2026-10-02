"""crm_mail.send_teacher_schedule — αναγνώσιμο μήνυμα όταν το CRM απορρίπτει.

Πριν: ένα 422 του CRM (λίστα σφαλμάτων επικύρωσης στο `detail`) γινόταν σκέτο
«CRM 422», και μια απάντηση JSON-λίστα έσκαγε με AttributeError.
"""
from __future__ import annotations

import httpx
import pytest

from backend.services import crm_mail


class _Res:
    def __init__(self, status_code, body=None, text=False):
        self.status_code = status_code
        self._body = body
        self._text = text

    def json(self):
        if self._text:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def respond(monkeypatch):
    monkeypatch.setattr(crm_mail, "_crm_config", lambda: ("http://crm", "tok"))

    def _set(res):
        class _Client:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, url, json, headers):
                assert url == "http://crm/api/eds-mail/teacher-schedule"
                assert headers == {"Authorization": "Bearer tok"}
                return res

        monkeypatch.setattr(httpx, "Client", _Client)

    return _set


def test_ok(respond):
    respond(_Res(200, {"ok": True}))
    assert crm_mail.send_teacher_schedule({}) == (True, None)


def test_string_detail_is_passed_through(respond):
    respond(_Res(500, {"detail": "SMTP down"}))
    assert crm_mail.send_teacher_schedule({}) == (False, "SMTP down")


def test_validation_list_becomes_readable_text(respond):
    detail = [{"loc": ["body", "groups", 0, "students"], "type": "string_too_long",
               "msg": "String should have at most 200 characters", "input": "x" * 250}]
    respond(_Res(422, {"detail": detail}))
    ok, msg = crm_mail.send_teacher_schedule({})
    assert ok is False
    assert msg == ("Το CRM απέρριψε τα δεδομένα (422): "
                   "groups.0.students: String should have at most 200 characters")
    assert "xxxx" not in msg            # η τιμή που απορρίφθηκε δεν μπαίνει στο μήνυμα


def test_long_validation_list_is_capped(respond):
    detail = [{"loc": ["body", "f", i], "msg": "bad"} for i in range(8)]
    respond(_Res(422, {"detail": detail}))
    _ok, msg = crm_mail.send_teacher_schedule({})
    assert msg.count("bad") == 5 and msg.endswith("(+3 ακόμα)")


@pytest.mark.parametrize("res", [_Res(502, text=True), _Res(400, ["unexpected"]),
                                 _Res(422, {"detail": [{"no": "msg"}]})])
def test_unreadable_bodies_fall_back_to_status(respond, res):
    respond(res)
    assert crm_mail.send_teacher_schedule({}) == (False, f"CRM {res.status_code}")
