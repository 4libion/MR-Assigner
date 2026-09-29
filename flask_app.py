"""Telegram webhook (Flask): Telegram POSTs every update to /webhook.

Use this when Telegram can reach the server over HTTPS.
"""

from __future__ import annotations

import os

from flask import Flask, abort, request

import bot

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]

app = Flask(__name__)


@app.post("/webhook")
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    try:
        bot.handle_update(request.get_json(silent=True) or {})
    except bot.RetryLater as e:
        bot.log.warning("Telegram unavailable, asking for redelivery: %s", e)
        return "retry", 503
    return "ok"


@app.get("/")
def health():
    return "mr-assigner is running"
