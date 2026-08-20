# 🌱 Shakahari

**Shakahari** is a serverless, agent-driven plant care system that runs for **$0/month**.

Unlike simple timer apps, Shakahari uses **Gemini 2.5 Flash** (AI), **Open-Meteo** (Weather), and **Google Sheets** (Memory) to intelligently manage the watering and fertilization schedules for your entire garden. It adjusts automatically for rain, heatwaves, seasons, and plant types.

## ✨ Features

- **🧠 Context-Aware Agent:** Analyzes recent rain history, temperature forecasts, and specific plant hardiness to decide if care is _actually_ needed.
- **📖 Plant-Specific Guidelines:** Uses [Perenual API](https://perenual.com) to fetch watering frequency for 10,000+ plant species.
- **📅 Days Tracking:** Calculates days since each action type (WATER, MIST, ROTATE, etc.) from CareHistory.
- **🛡️ Safety Filters:** Won't recommend watering if < 3 days since last watering, rotating if < 7 days, etc.
- **🌦️ Weather Integrated:** Automatically skips watering outdoor plants if it rained.
- **💬 Instant Feedback:** Receive daily digest via **Telegram**. Tap buttons to log actions instantly, or send `/log` anytime to log actions not on the digest.
- **📂 Serverless:** Runs on a scheduled GitHub Action (Cron). No AWS/GCP bills.


## 🏗️ Architecture

```mermaid
flowchart TD
    A[Daily Trigger] -->|1. Wake Up| B[Main Script]
    B -->|2. Get Context| C[Fetch Weather]
    B -->|3. Get Inventory| D[Google Sheets DB]
    B -->|4. Ask Agent| E[Gemini AI]
    E -->|5. Decisions| F{Tasks Needed}
    F -->|Yes| G[Send Telegram Digest]
    F -->|No| H[Sleep]
    
    I[User Taps Button/Sends /log] -->|Instant| J[Cloud Function Webhook]
    J -->|Update| K[Google Sheets DB]
    G -.->|Includes Buttons| I
```

## 🛠️ Prerequisites

You will need free accounts for the following services:

1. **Google Cloud Project:** For the Gemini API and Google Sheets API.
2. **Telegram:** To create the bot.
3. **GitHub:** To host the code and run the runner.

## 🚀 Installation & Setup

### 1. Database Setup (Google Sheets)

1. Create a new Google Sheet named `ShakahariDB`.
2. Rename the first tab to `Plants`.
3. Add the following headers:

   | Name | Environment | Light | Humidity | Notes | Last Watered | Last Fertilized | Status |
   |------|-------------|-------|----------|-------|--------------|-----------------|--------|

   - **Environment**: `indoor`, `outdoor`, `balcony`, or `greenhouse`
   - **Light**: `direct`, `indirect`, `low`, or `shade`
   - **Humidity**: `low`, `medium`, or `high`

4. **CareHistory Tab** (auto-created on first run):

   | Date | Plant | Action | Notes |
   |------|-------|--------|-------|

   This tab logs all care actions you confirm, giving the AI context to avoid recommending recently-performed tasks.

5. **Important:** Create a **Service Account** in Google Cloud Console, download the JSON key, and **share** your Google Sheet with the service account's email address (Editor access).

### 2. Telegram Bot Setup

1. Open Telegram and chat with **@BotFather**.
2. Send `/newbot` to create a bot and get your **API Token**.
3. Send a message to your new bot.
4. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` to find your `chat_id`.

### 3. Repository Configuration

1. Clone this repository.
2. Go to **Settings > Secrets and variables > Actions** in your GitHub repo.
3. Add the following Repository Secrets:

   | Secret Name | Value |
   |-------------|-------|
   | `GEMINI_API_KEY` | Your Google AI Studio API Key |
   | `TELEGRAM_TOKEN` | Your Bot Token from BotFather |
   | `TELEGRAM_CHAT_ID` | Your personal Chat ID |
   | `G_SHEET_CREDENTIALS` | The **entire content** of your Service Account JSON file |

### 4. Code Configuration

Open `src/config.py` and update your location:

```python
LATITUDE = 34.05  # Your Latitude
LONGITUDE = -118.25 # Your Longitude
SHEET_NAME = "ShakahariDB" # The google sheet name
```

### 5. Deploy

Push your code to GitHub. The workflow is defined in `.github/workflows/daily.yml` and is set to run automatically every morning (default: 14:00 UTC).

### 6. Real-Time Logging Setup (Google Cloud Function)

Digest buttons and `/log` need to be acknowledged within seconds, which the
once-a-day GitHub Actions cron can't do. A small always-on Cloud Function
handles this instead — Google's free tier (2M invocations/month) comfortably
covers a personal bot's traffic.

1. **Generate a webhook secret** (any random string) and add it to your
   `.env` as `TELEGRAM_WEBHOOK_SECRET`, and to your shell environment (the
   `setWebhook` call in step 4 reads it from there).

2. **Create an `env.yaml`** in the repo root holding the function's four
   environment variables:

   ```yaml
   TELEGRAM_TOKEN: "123456789:AA-your-bot-token"
   TELEGRAM_CHAT_ID: "987654321"
   TELEGRAM_WEBHOOK_SECRET: "your-random-webhook-secret"
   G_SHEET_CREDENTIALS: '{"type": "service_account", "project_id": "your-project", "private_key": "-----BEGIN PRIVATE KEY-----\nMII...\n-----END PRIVATE KEY-----\n", "client_email": "shakahari@your-project.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token"}'
   ```

   Keep `G_SHEET_CREDENTIALS` on one line in **single** quotes — single-quoted
   YAML passes the JSON's `\n` escapes through untouched, which the private key
   needs. (A file is required rather than `--set-env-vars` because that flag
   splits on commas, and the service-account JSON is full of them — gcloud fails
   with `Bad syntax for dict arg` before it ever reaches the API.)

   > ⚠️ **Never commit `env.yaml`** — it holds your bot token and your service
   > account's private key. It is already listed in `.gitignore`.

3. **Deploy the function** (from the repo root):

   ```bash
   gcloud functions deploy shakahari-recorder \
     --gen2 \
     --runtime=python312 \
     --region=us-west1 \
     --source=. \
     --entry-point=telegram_webhook \
     --trigger-http \
     --allow-unauthenticated \
     --env-vars-file=env.yaml
   ```

   Note the `httpsTrigger.url` printed at the end — you'll need it next.

4. **Register the webhook with Telegram:**

   ```bash
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
     -d "url=${CLOUD_FUNCTION_URL}" \
     -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
   ```

5. **Verify it's registered:**

   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
   ```

   Expect the response's `"url"` to match your function's URL and
   `"last_error_message"` to be absent.

> A webhook and `getUpdates` polling are mutually exclusive — once this is
> registered, nothing in this repo calls `getUpdates` anymore (the Advisor's
> `sync_from_mailbox()` was removed for exactly this reason).

> The secret token only proves an update came from Telegram, not who sent it, so
> the Recorder additionally ignores anything that isn't from `TELEGRAM_CHAT_ID`.
> If buttons and `/log` do nothing, check that value first.

## 📱 Usage Guide

### The Daily Notification

Every morning, if action is required, Shakahari sends you a compact digest —
one line per task showing a deterministic days-since-vs-threshold code
instead of a full sentence, so a large backlog stays scannable:

> 🌿 **Plant Care Tasks (2026-01-22)**  
>_All plants generally healthy._
>
> 🔴💧 **Monstera** — 12d≥10d  
> 🟡💧 **Peace Lily** — 18d≥14d  
> 🟢🔄 **Pothos** — 9d≥7d  

Each line has its own named button underneath (e.g. "💧 Water Monstera"),
plus a "Mark watering complete" / "Mark rotating complete" style button per
action type actually present, and a final "Mark everything above done".

### Interacting with the Bot

Every task in the daily digest has its own named button:

- **Tap a task's button** (e.g. "💧 Water Monstera") to log it instantly —
  the button changes to a checkmark and a toast confirms it, all within the
  same message. Nothing new is added to the chat, so you never lose your
  scroll position.
- **Tap "Mark watering complete"** (or fertilizing / rotating / etc. — one
  button per action type actually in today's digest) to confirm every plant
  currently needing that action in one tap.
- **Tap "✅ Mark everything above done"** to confirm every pending task at once.
- Not doing something today? Just don't tap its button — there's no
  separate "skip" action; the agent reconsiders anything still pending
  again tomorrow.

**Logging anything else:** send `/log` at any time to log an action that
wasn't on the digest — pick a plant, then pick what you did. This works
independently of whatever the agent last recommended.

> Both paths are handled instantly by a Cloud Function webhook (see
> "Real-time logging setup" below) — not the daily cron job.

## 📂 Project Structure

```
/
├── .github/workflows/   # Cron schedule configuration
├── src/
│   ├── agent.py         # Gemini AI Logic (Prompt Engineering)
│   ├── config.py        # Configuration & Env Vars
│   ├── storage.py       # Google Sheets DB & Care Logging
│   ├── telegram_bot.py  # Notification Service
│   ├── recorder.py      # Cloud Function for Real-Time Logging
│   └── weather.py       # Open-Meteo Integration
├── main.py              # Entry point (Advisor cron job)
└── requirements.txt     # Python dependencies
```

## 🤝 Contributing

Feel free to fork this project and add features like:

- Photo analysis (upload a photo to check for pests).
- Hardware integration (ESP32 soil sensors).

## 📄 License

MIT License. Free to use and modify.
