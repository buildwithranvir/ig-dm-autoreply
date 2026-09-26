# Instagram DM assistant

Replies to DMs on @buildwithranvir in Ranvir's voice using the official Instagram API with
Instagram Login. Runs on Vercel (free) with Upstash Redis and a Groq-hosted LLM.

## What it does

- Replies to followers, and to message requests from accounts that look real (verified, or a
  profile picture and at least 10 followers). Replying moves a request to General.
- Answers small talk on its own and steers idle chats toward why the person messaged.
- Only states facts from `knowledge/`. Anything else becomes a question for you (see below).
- Hands the chat to you (and stays quiet for 24h) for brand deals, complaints, personal topics or
  requests to talk to you directly. Replying yourself in the Instagram app also pauses it for 24h.
- The first reply in each conversation is marked as AI-written.

## Your alert account

Alerts and questions go to your second account (`OWNER_ALERT_IGSID`). Instagram only allows the bot
to message it within 24 hours of its last message, so alerts queue until you write to the bot.

| Send                                  | Effect                                                     |
|---------------------------------------|------------------------------------------------------------|
| swipe-reply to a ❓ alert with the answer | Answers that question; the AI relays it in your voice  |
| `12 answer`                           | Answers question #12                                       |
| just the answer                       | Answers the only open question (asks which if several)     |
| `save` before any answer              | Also remembers the answer for future chats                 |
| `inbox`                               | Delivers queued alerts                                     |
| `reset`                               | Clears your own test chat with the bot                     |
| anything else, with no open questions | Chats with the AI like a normal user (for testing)         |

## Project layout

```
app/
  main.py          HTTP routes: webhook, token-refresh cron, privacy page
  bot.py           What happens to each incoming message
  ai.py            Prompt and LLM call
  screening.py     Which chats and message requests to answer
  config.py        Settings from environment variables
  instagram/       Instagram API calls, sending messages, access token refresh
  owner/           Alerts and questions sent to your alert account
  storage/         Redis (or in-memory) storage and per-chat history
knowledge/         persona.md and faq.md: the only facts the AI may state
scripts/           whoami.py and subscribe.py for first-time setup
tests/             pytest suite (no network access needed)
```

## Local development

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
copy .env.example .env        # then fill it in
.venv\Scripts\python -m pytest
.venv\Scripts\uvicorn app.main:app --port 8000
```

Without Upstash credentials, storage is in memory and resets on restart.

## Deploying

The Vercel project is linked to this repo: every push to `main` deploys to production
automatically. `vercel deploy --prod` still works for a manual deploy.

Settings live in the Vercel project's environment variables; `vercel.json` schedules the daily
token-refresh cron. Changes to `knowledge/` take effect once they are pushed.
