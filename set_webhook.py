"""Point Telegram at the webhook, show its status, or remove it (needed before poll.py).

Usage:
    python set_webhook.py https://<username>.pythonanywhere.com/webhook
    python set_webhook.py --info
    python set_webhook.py --delete
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
API_URL = f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}"

if len(sys.argv) != 2:
    sys.exit(__doc__)

if sys.argv[1] == "--info":
    resp = requests.get(f"{API_URL}/getWebhookInfo", timeout=10)
elif sys.argv[1] == "--delete":
    resp = requests.post(f"{API_URL}/deleteWebhook", timeout=10)
else:
    resp = requests.post(
        f"{API_URL}/setWebhook",
        json={
            "url": sys.argv[1],
            "secret_token": os.environ["WEBHOOK_SECRET"],
            "allowed_updates": ["message"],
            "max_connections": 1,
        },
        timeout=10,
    )
print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
