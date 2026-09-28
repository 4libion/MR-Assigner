"""Telegram webhook (Flask) that assigns PR/MR links posted in a group to reviewers round-robin.

Telegram POSTs every update to /webhook; the app replies through the Bot API.
"""

from __future__ import annotations

import html
import json
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, request

from assigner import Reviewer, State, extract_links, pick_reviewer

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", BASE_DIR / "config.json"))
STATE_PATH = Path(os.environ.get("STATE_PATH", BASE_DIR / "data" / "state.json"))
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("mr-assigner")

config = json.loads(CONFIG_PATH.read_text())
REVIEWERS = [Reviewer(**r) for r in config["reviewers"]]
ALLOWED_CHAT_ID: int | None = config.get("chat_id")

app = Flask(__name__)
_bot_username: str | None = None


class RetryLater(Exception):
    """Telegram is unreachable or overloaded; let it redeliver the update."""


def call_api(method: str, **params) -> dict:
    try:
        resp = requests.post(f"{API_URL}/{method}", json=params, timeout=10)
    except requests.RequestException as e:
        raise RetryLater(f"{method}: {e}") from e
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryLater(f"{method}: HTTP {resp.status_code} {resp.text}")
    return resp.json()


def reply(msg: dict, text: str) -> bool:
    result = call_api(
        "sendMessage",
        chat_id=msg["chat"]["id"],
        text=text,
        parse_mode="HTML",
        link_preview_options={"is_disabled": True},
        reply_parameters={"message_id": msg["message_id"], "allow_sending_without_reply": True},
    )
    if not result.get("ok"):
        log.error("sendMessage failed: %s", result)
    return bool(result.get("ok"))


def bot_username() -> str | None:
    global _bot_username
    if _bot_username is None:
        try:
            _bot_username = call_api("getMe")["result"]["username"].lower()
        except (RetryLater, KeyError) as e:
            log.warning("getMe failed: %s", e)
    return _bot_username


def parse_command(text: str) -> str | None:
    """'/queue@MyBot args' -> 'queue', or None if it's not a command for this bot."""
    if not text.startswith("/"):
        return None
    cmd, _, target = text.split()[0][1:].partition("@")
    if target and (me := bot_username()) and target.lower() != me:
        return None
    return cmd.lower()


def mention(r: Reviewer) -> str:
    if r.username:
        return f"@{html.escape(r.username)}"
    return f'<a href="tg://user?id={r.id}">{html.escape(r.name)}</a>'


def message_links(msg: dict) -> list[str]:
    """Links from the visible text plus hyperlinks hidden behind other text."""
    text = msg.get("text") or msg.get("caption") or ""
    entities = msg.get("entities") or msg.get("caption_entities") or []
    hidden = " ".join(e["url"] for e in entities if e.get("url"))
    return extract_links(f"{text} {hidden}")


def handle_whoami(msg: dict) -> None:
    user = msg["from"]
    reply(
        msg,
        f"user id: {user['id']}\n"
        f"username: {html.escape(user.get('username') or '-')}\n"
        f"chat id: {msg['chat']['id']}",
    )


def handle_queue(msg: dict) -> None:
    if not REVIEWERS:
        reply(msg, "The reviewer list is empty.")
        return
    state = State(STATE_PATH)
    n = len(REVIEWERS)
    order = [REVIEWERS[(state.next_index + i) % n] for i in range(n)]
    reply(msg, "Queue (next first):\n" + "\n".join(
        f"{i}. {html.escape(r.name)}" for i, r in enumerate(order, 1)
    ))


def handle_links(msg: dict) -> None:
    if msg["chat"]["type"] not in ("group", "supergroup"):
        return
    state = State(STATE_PATH)
    new_links = [link for link in message_links(msg) if link not in state.assigned]
    if not new_links:
        return

    author_id = msg["from"]["id"]
    lines = []
    for link in new_links:
        reviewer = pick_reviewer(REVIEWERS, state, author_id)
        if reviewer is None:
            lines.append(f"{html.escape(link)} → no available reviewer")
            continue
        state.assigned[link] = reviewer.id
        lines.append(f"{html.escape(link)} → {mention(reviewer)}")

    # Save only after the reply went out, so a failed send doesn't burn a turn.
    if reply(msg, "Review assigned:\n" + "\n".join(lines)):
        state.save()
        log.info("Assigned: %s (author %s)", "; ".join(lines), author_id)


@app.post("/webhook")
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)

    msg = (request.get_json(silent=True) or {}).get("message")
    if not msg or "from" not in msg:
        return "ok"
    if ALLOWED_CHAT_ID is not None and msg["chat"]["id"] != ALLOWED_CHAT_ID:
        return "ok"

    try:
        cmd = parse_command(msg.get("text", ""))
        if cmd == "whoami":
            handle_whoami(msg)
        elif cmd == "queue":
            handle_queue(msg)
        elif cmd is None:
            handle_links(msg)
    except RetryLater as e:
        log.warning("Telegram unavailable, asking for redelivery: %s", e)
        return "retry", 503
    return "ok"


@app.get("/")
def health():
    return "mr-assigner is running"
