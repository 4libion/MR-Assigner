"""Telegram bot logic shared by the webhook (flask_app.py) and the long-polling runner (poll.py):
assigns PR/MR links posted in a group to reviewers round-robin, and reminds them about open reviews.
"""

from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from assigner import Reviewer, State, due_reminder, extract_links, pick_reviewer
from gitlab_client import GitLab

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", BASE_DIR / "config.json"))
STATE_PATH = Path(os.environ.get("STATE_PATH", BASE_DIR / "data" / "state.json"))
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Almaty"))
REMIND_TIMES = [
    time.fromisoformat(t.strip())
    for t in os.environ.get("REMIND_TIMES", "09:00,14:00").split(",")
    if t.strip()
]
GITLAB = (
    GitLab(os.environ["GITLAB_URL"], os.environ.get("GITLAB_TOKEN", ""))
    if os.environ.get("GITLAB_URL")
    else None
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("mr-assigner")

config = json.loads(CONFIG_PATH.read_text())
REVIEWERS = [Reviewer(**r) for r in config["reviewers"]]
REVIEWERS_BY_ID = {r.id: r for r in REVIEWERS}
ALLOWED_CHAT_ID: int | None = config.get("chat_id")

_bot_username: str | None = None


class RetryLater(Exception):
    """Telegram is unreachable or overloaded; handle the update again later."""


def call_api(method: str, **params) -> dict:
    # getUpdates holds the request open for `timeout` seconds, so wait longer than that.
    http_timeout = params.get("timeout", 0) + 10
    try:
        resp = requests.post(f"{API_URL}/{method}", json=params, timeout=http_timeout)
    except requests.RequestException as e:
        raise RetryLater(f"{method}: {e}") from e
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RetryLater(f"{method}: HTTP {resp.status_code} {resp.text}")
    return resp.json()


def send(chat_id: int, text: str, reply_to: int | None = None) -> bool:
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if reply_to is not None:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    result = call_api("sendMessage", **params)
    if not result.get("ok"):
        log.error("sendMessage failed: %s", result)
    return bool(result.get("ok"))


def reply(msg: dict, text: str) -> bool:
    return send(msg["chat"]["id"], text, reply_to=msg["message_id"])


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


def open_reviews(state: State, reviewer_id: int | None = None) -> dict[int, list[str]]:
    """Reviewer id -> GitLab MRs assigned to them that aren't approved, merged or closed yet.

    Checks each MR in GitLab and records finished ones in state.done; the caller
    saves the state. MRs whose status couldn't be read are listed with a note.
    """
    result: dict[int, list[str]] = {}
    for link, rid in state.assigned.items():
        if link in state.done or (reviewer_id is not None and rid != reviewer_id):
            continue
        if not GITLAB.tracks(link):
            continue
        done = GITLAB.is_done(link)
        if done:
            state.done.add(link)
            continue
        line = html.escape(link) + (" (couldn't check status)" if done is None else "")
        result.setdefault(rid, []).append(line)
    return result


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


def handle_my(msg: dict) -> None:
    if GITLAB is None:
        reply(msg, "GitLab isn't connected, so the bot can't see which MRs are approved.")
        return
    state = State(STATE_PATH)
    links = open_reviews(state, msg["from"]["id"]).get(msg["from"]["id"], [])
    state.save()
    if links:
        reply(msg, "Waiting for your review:\n" + "\n".join(f"• {link}" for link in links))
    else:
        reply(msg, "Nothing is waiting for your review.")


def handle_links(msg: dict) -> None:
    if msg["chat"]["type"] not in ("group", "supergroup"):
        return
    state = State(STATE_PATH)
    new_links = [link for link in message_links(msg) if link not in state.assigned]
    if not new_links:
        return

    author_id = msg["from"]["id"]
    lines = []
    picked: list[tuple[str, Reviewer]] = []
    for link in new_links:
        reviewer = pick_reviewer(REVIEWERS, state, author_id)
        if reviewer is None:
            lines.append(f"{html.escape(link)} → no available reviewer")
            continue
        state.assigned[link] = reviewer.id
        picked.append((link, reviewer))
        lines.append(f"{html.escape(link)} → {mention(reviewer)}")

    # Save only after the reply went out, so a failed send doesn't burn a turn.
    if not reply(msg, "Review assigned:\n" + "\n".join(lines)):
        return
    state.save()
    log.info("Assigned: %s (author %s)", "; ".join(lines), author_id)
    set_gitlab_reviewers(msg, picked)


def set_gitlab_reviewers(msg: dict, picked: list[tuple[str, Reviewer]]) -> None:
    """Add the picked reviewers to their MRs in GitLab; say in the chat if that fails."""
    if GITLAB is None:
        return
    failed = [
        link
        for link, reviewer in picked
        if GITLAB.tracks(link) and reviewer.gitlab
        and not GITLAB.add_reviewer(link, reviewer.gitlab)
    ]
    if failed:
        reply(msg, "Couldn't set the reviewer in GitLab for:\n" + "\n".join(
            html.escape(link) for link in failed
        ))


def handle_update(update: dict) -> None:
    """Handle one Telegram update. Raises RetryLater if Telegram is unavailable."""
    msg = update.get("message")
    if not msg or "from" not in msg:
        return
    if ALLOWED_CHAT_ID is not None and msg["chat"]["id"] != ALLOWED_CHAT_ID:
        return

    cmd = parse_command(msg.get("text", ""))
    if cmd == "whoami":
        handle_whoami(msg)
    elif cmd == "queue":
        handle_queue(msg)
    elif cmd == "my":
        handle_my(msg)
    elif cmd is None:
        handle_links(msg)


def remind_if_due(now: datetime | None = None) -> None:
    """Post the open reviews to the group when a reminder slot comes up.

    Raises RetryLater if Telegram is unavailable; the slot stays due and is retried.
    """
    if GITLAB is None or ALLOWED_CHAT_ID is None:
        return
    now = now or datetime.now(TIMEZONE)
    state = State(STATE_PATH)
    slot = due_reminder(now, state.last_reminder, REMIND_TIMES)
    if slot is None:
        return

    sections = [
        f"{mention(REVIEWERS_BY_ID[rid])}:\n" + "\n".join(f"• {link}" for link in links)
        for rid, links in open_reviews(state).items()
        if rid in REVIEWERS_BY_ID
    ]
    if sections:
        send(ALLOWED_CHAT_ID, "MRs waiting for review:\n\n" + "\n\n".join(sections))
    state.last_reminder = slot
    state.save()
    log.info("Reminder for %s sent to %d reviewer(s)", slot, len(sections))
