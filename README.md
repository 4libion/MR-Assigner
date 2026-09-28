# mr-assigner

A Telegram bot for group chats. When someone posts a GitHub PR link (or a GitLab MR link), the bot replies to that message and tags the next reviewer in a round-robin queue.

- Each link gets its own reviewer.
- The author of the message is never assigned their own PR. If it's their turn, the bot skips to the next person.
- If a link was already assigned, the bot ignores it when it's posted again.
- The bot saves the queue position and the assigned links in `data/state.json`.

It runs as a small Flask app. Telegram sends each group message to `/webhook` (a webhook), and the app replies through the Bot API. This fits the free tier of [PythonAnywhere](https://www.pythonanywhere.com), which needs no card.

## Files

| File | Purpose |
|---|---|
| `flask_app.py` | Receives messages from Telegram and replies |
| `assigner.py` | Link detection, round-robin choice, saved state |
| `set_webhook.py` | Tells Telegram where to send messages |
| `config.json` | Reviewers and the group's chat ID (not in git) |
| `.env` | Bot token and webhook secret (not in git) |

## 1. Telegram setup

1. In [@BotFather](https://t.me/BotFather), run `/newbot` and copy the token.
2. Let the bot read group messages: `/setprivacy` → pick your bot → **Disable**. Do this before adding the bot to the group; if it's already there, remove it and add it back.

## 2. PythonAnywhere setup

1. **Sign up** for a free "Beginner" account. Your site will be `https://<username>.pythonanywhere.com`. If the bot belongs to a team, sign up with a shared team email rather than a personal one.
2. **Get the code:** open **Consoles → Bash** and run:
   ```bash
   git clone https://github.com/<you>/mr-assigner.git
   cd mr-assigner
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. **Create `.env`:**
   ```bash
   cp .env.example .env
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # generates WEBHOOK_SECRET
   nano .env    # paste BOT_TOKEN and WEBHOOK_SECRET, save with Ctrl+O, exit with Ctrl+X
   ```
4. **Create `config.json`.** Upload yours through the **Files** tab, or start with an empty list to collect user IDs first (see section 3):
   ```bash
   echo '{"chat_id": null, "reviewers": []}' > config.json
   ```
5. **Create the web app:** on the **Web** tab, choose **Add a new web app** → **Manual configuration** → the newest Python version offered. Then, on the same page:
   - **Virtualenv:** `/home/<username>/mr-assigner/.venv`
   - **WSGI configuration file:** click the link and replace the whole file with:
     ```python
     import sys
     sys.path.insert(0, "/home/<username>/mr-assigner")
     from flask_app import app as application
     ```
   - Click **Reload**. Opening `https://<username>.pythonanywhere.com` should show "mr-assigner is running".

   The Python version for the web app must match the one used to create the venv in step 2 (`python3 --version` in the Bash console shows it). If they differ, create the venv with the matching version, e.g. `python3.12 -m venv .venv`.
6. **Connect Telegram:** in the Bash console, run:
   ```bash
   cd ~/mr-assigner
   .venv/bin/python set_webhook.py https://<username>.pythonanywhere.com/webhook
   ```
   The output should include `"ok": true`.

## 3. Fill in the reviewers

1. Add the bot to the group. Each developer sends `/whoami` there, and the bot replies with their user ID and the chat ID.
2. Edit `config.json` on the **Files** tab:
   ```json
   {
     "chat_id": -1001234567890,
     "reviewers": [
       {"id": 111111111, "name": "Alice", "username": "alice_dev"},
       {"id": 222222222, "name": "Bob"}
     ]
   }
   ```
   - `chat_id` limits the bot to your group. `null` allows any group.
   - `username` is optional. Without it, the bot mentions the person by name through their user ID, which still sends them a notification.
   - The queue follows the order of this list.
3. Click **Reload** on the **Web** tab.

## Commands

- `/queue`: shows the reviewer order, with the next reviewer first.
- `/whoami`: shows your user ID and the chat ID.

## Maintenance

- **Every 3 months**, click **"Run until 3 months from today"** on the **Web** tab. Otherwise the free web app is disabled and the bot stops replying. PythonAnywhere sends a reminder email first.
- **Team changes:** edit `config.json`, then click **Reload**.
- **Code changes:** run `cd ~/mr-assigner && git pull` in a Bash console, then click **Reload**.
- **Troubleshooting:** check the **error log** link on the **Web** tab, and run `.venv/bin/python set_webhook.py --info`. Its `last_error_message` field shows why Telegram couldn't deliver messages.

If PythonAnywhere is briefly down, Telegram keeps the messages and delivers them later.

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests
```
