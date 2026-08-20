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
   `.env` as `TELEGRAM_WEBHOOK_SECRET`, and to your shell environment before
   deploying.

2. **Deploy the function** (from the repo root):

   ```bash
   gcloud functions deploy shakahari-recorder \
     --gen2 \
     --runtime=python312 \
     --region=us-west1 \
     --source=. \
     --entry-point=telegram_webhook \
     --trigger-http \
     --allow-unauthenticated \
     --set-env-vars=TELEGRAM_TOKEN="$TELEGRAM_TOKEN",TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID",G_SHEET_CREDENTIALS="$G_SHEET_CREDENTIALS",TELEGRAM_WEBHOOK_SECRET="$TELEGRAM_WEBHOOK_SECRET"
   ```

   Note the `httpsTrigger.url` printed at the end — you'll need it next.

3. **Register the webhook with Telegram:**

   ```bash
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
     -d "url=${CLOUD_FUNCTION_URL}" \
     -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
   ```

4. **Verify it's registered:**

   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
   ```

   Expect the response's `"url"` to match your function's URL and
   `"last_error_message"` to be absent.

> A webhook and `getUpdates` polling are mutually exclusive — once this is
> registered, nothing in this repo calls `getUpdates` anymore (the Advisor's
> `sync_from_mailbox()` was removed for exactly this reason).

## 📱 Usage Guide

### The Daily Notification

Every morning, if action is required, Shakahari sends you a digest grouped by action type:

> 🌿 **Plant Care Tasks (2026-01-22)**  
>_All plants generally healthy._
>
> 💧 **WATER**: Monstera, Peace Lily, Fern  
> 🔄 **ROTATE**: Pothos  
> 🧪 **FERTILIZE**: Fiddle Leaf 
>
> **Details:**  
> 🔴💧 **Monstera**: Soil dry after 8 days, indoor heat accelerates drying  
> 🟡💧 **Peace Lily**: Low humidity environment needs more frequent watering  
> 🟢🔄 **Pothos**: Leaves leaning toward window, rotate for even growth
>
> _(Buttons under the message allow you to log these actions instantly)_  

### Interacting with the Bot

Every task in the daily digest has its own buttons:

- **Tap the action button** (e.g. "💧 Watered") to log it instantly — the
  button changes to a checkmark and a toast confirms it, all within the
  same message. Nothing new is added to the chat, so you never lose your
  scroll position.
- **Tap "⏭ Skip today"** to clear that task without logging it as done —
  the agent will reconsider it fresh tomorrow.
- **Tap "✅ Mark everything above done"** to confirm every pending task at once.

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
