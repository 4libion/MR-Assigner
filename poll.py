"""Run the bot with long polling: it asks Telegram for new messages itself, so the
server needs no public address.

Usage:
    python poll.py
"""

from __future__ import annotations

import sys
import time

import bot

POLL_SECONDS = 30  # how long Telegram holds each getUpdates request open
RETRY_SECONDS = 5


def main() -> None:
    offset = None
    bot.log.info("Polling Telegram for updates")
    while True:
        try:
            result = bot.call_api(
                "getUpdates", offset=offset, timeout=POLL_SECONDS, allowed_updates=["message"]
            )
        except bot.RetryLater as e:
            bot.log.warning("Telegram unavailable: %s", e)
            time.sleep(RETRY_SECONDS)
            continue

        if result.get("error_code") == 409:
            sys.exit("A webhook is set for this bot. Remove it first: python set_webhook.py --delete")
        if not result.get("ok"):
            bot.log.error("getUpdates failed: %s", result)
            time.sleep(RETRY_SECONDS)
            continue

        for update in result["result"]:
            while True:
                try:
                    bot.handle_update(update)
                    break
                except bot.RetryLater as e:
                    bot.log.warning("Telegram unavailable, retrying update: %s", e)
                    time.sleep(RETRY_SECONDS)
                except Exception:
                    bot.log.exception("Update %s failed, skipping it", update.get("update_id"))
                    break
            offset = update["update_id"] + 1


if __name__ == "__main__":
    main()
