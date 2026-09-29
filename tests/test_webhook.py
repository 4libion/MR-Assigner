import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SECRET = "test-secret"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
GROUP = {"id": -100, "type": "supergroup"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = {
        "chat_id": -100,
        "reviewers": [
            {"id": 1, "name": "Alice", "username": "alice"},
            {"id": 2, "name": "Bob"},
        ],
    }
    (tmp_path / "config.json").write_text(json.dumps(config))
    monkeypatch.setenv("BOT_TOKEN", "1:x")
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "data" / "state.json"))
    sys.modules.pop("bot", None)
    sys.modules.pop("flask_app", None)
    import bot
    import flask_app

    sent = []

    def fake_call_api(method, **params):
        if method == "getMe":
            return {"ok": True, "result": {"username": "MrBot"}}
        sent.append(params)
        return {"ok": True}

    monkeypatch.setattr(bot, "call_api", fake_call_api)
    c = flask_app.app.test_client()
    c.sent = sent
    c.bot = bot
    return c


def post(client, text, user_id=9, chat=GROUP, headers=HEADERS):
    msg = {"message_id": 5, "chat": chat, "from": {"id": user_id}, "text": text}
    return client.post("/webhook", json={"message": msg}, headers=headers)


def test_rejects_wrong_secret(client):
    assert post(client, "hi", headers={}).status_code == 403


def test_assigns_round_robin_and_skips_author(client):
    post(client, "https://github.com/o/r/pull/1")
    post(client, "https://github.com/o/r/pull/2", user_id=1)  # Bob is next
    post(client, "https://github.com/o/r/pull/3", user_id=1)  # Alice is next but is the author
    texts = [s["text"] for s in client.sent]
    assert "@alice" in texts[0]
    assert "Bob" in texts[1]
    assert "Bob" in texts[2]
    assert client.sent[0]["reply_parameters"]["message_id"] == 5


def test_ignores_repeated_link(client):
    post(client, "https://github.com/o/r/pull/1")
    post(client, "again: https://github.com/o/r/pull/1/files")
    assert len(client.sent) == 1


def test_one_reviewer_per_link(client):
    post(client, "https://github.com/o/r/pull/1 https://github.com/o/r/pull/2")
    text = client.sent[0]["text"]
    assert "@alice" in text and "Bob" in text


def test_ignores_other_chats_and_private(client):
    post(client, "https://github.com/o/r/pull/1", chat={"id": -999, "type": "group"})
    assert client.sent == []


def test_commands(client):
    post(client, "/whoami")
    post(client, "/queue@MrBot")
    post(client, "/queue@OtherBot")
    assert len(client.sent) == 2
    assert "user id: 9" in client.sent[0]["text"]
    assert client.sent[1]["text"].startswith("Queue (next first):\n1. Alice")


def test_failed_send_does_not_consume_turn(client, monkeypatch):
    monkeypatch.setattr(client.bot, "call_api", lambda method, **p: {"ok": False})
    post(client, "https://github.com/o/r/pull/1")
    assert not Path(os.environ["STATE_PATH"]).exists()


def test_telegram_down_asks_for_retry(client, monkeypatch):
    def down(method, **p):
        raise client.bot.RetryLater("down")

    monkeypatch.setattr(client.bot, "call_api", down)
    assert post(client, "https://github.com/o/r/pull/1").status_code == 503
