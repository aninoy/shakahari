# 🌱 Shakahari

**Shakahari** is a serverless, agent-driven plant care system that runs for **$0/month**.

Unlike simple timer apps, Shakahari uses **Gemini 2.5 Flash** (AI), **Open-Meteo** (Weather), and **Google Sheets** (Memory) to intelligently manage the watering and fertilization schedules for your entire garden. It adjusts automatically for rain, heatwaves, seasons, and plant types.

## ✨ Features

- **🧠 Context-Aware Agent:** Analyzes recent rain history, temperature forecasts, and specific plant hardiness to decide if care is _actually_ needed.
- **📖 Plant-Specific Guidelines:** Uses [Perenual API](https://perenual.com) to fetch watering frequency for 10,000+ plant species.
- **📅 Days Tracking:** Calculates days since each action type (WATER, MIST, ROTATE, etc.) from CareHistory.
- **🌡️ Computed Intervals:** Every plant gets its own schedule per action, derived from evapotranspiration, rain (past *and* forecast), humidity, daylight-based season, and how it is watered — not a fixed table. The digest shows its work (`🔁10d→8d (high ET₀)`).
- **🧪 Per-Product Feeding:** Fertilizing is grouped by bottle, so one "done" tap means one real-world act with one product.
- **🌦️ Weather Integrated:** Skips watering outdoor plants when it has rained or is about to, and ignores rain entirely for indoor ones.
- **🚿 Irrigation Aware:** Plants on a sprinkler or drip line never generate watering reminders you cannot act on.
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

1. **Google Cloud Project:** For the Gemini API, Google Sheets API, and the
   Cloud Function that handles real-time logging. Cloud Functions (gen2)
   require a **billing account attached** to the project — even to stay
   within the free tier — so link one in the
   [Cloud Console billing page](https://console.cloud.google.com/billing)
   before deploying (see "Real-Time Logging Setup" below).
2. **Telegram:** To create the bot.
3. **GitHub:** To host the code and run the runner.

## 🚀 Installation & Setup

### 1. Database Setup (Google Sheets)

1. Create a new Google Sheet named `ShakahariDB`.
2. Rename the first tab to `Plants`.
3. Add the following headers:

   | Name | Environment | Light | Humidity | Notes | Last Watered | Last Fertilized | Status | Fertilizer | Watering |
   |------|-------------|-------|----------|-------|--------------|-----------------|--------|------------|----------|

   - **Environment**: `indoor`, `outdoor`, `balcony`, or `greenhouse`
   - **Light**: `direct`, `indirect`, `low`, or `shade`
   - **Humidity**: `low`, `medium`, or `high`
   - **Fertilizer**: which product this plant gets — `CITRUS`, `ACID`, `BLOOM`,
     `GRANULAR`, `ALLPURPOSE`, `ALLPURPOSE_HALF`, or `SUCCULENT`
     (see `src/fertilizers.py`). Blank lands the plant in a visible
     "❓ Not set" group rather than defaulting to a product — feeding the wrong
     fertilizer is worse than not feeding.
   - **Watering**: how it gets watered — `manual` (default when blank),
     `sprinkler`, `drip`, or `established`. Irrigated plants produce no
     watering or misting tasks; in-ground ones produce no rotate, repot or
     move tasks.

   Run `python scripts/dry_run.py --table` to print paste-ready values for
   both new columns.

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

1. **Enable the required APIs** on your project (one-time):

   ```bash
   gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
     cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```

2. **Generate a webhook secret** (any random string, e.g.
   `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`) and add
   it to your `.env` as `TELEGRAM_WEBHOOK_SECRET`, and to your shell
   environment (the `setWebhook` call in step 5 reads it from there).

3. **Create an `env.yaml`** in the repo root holding the function's four
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

4. **Deploy the function** (from the repo root):

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

   The output lists two different URLs — grab **`serviceConfig.uri`** (a
   `.run.app` address), not the legacy `cloudfunctions.net` URL also shown.
   You can fetch it on its own later with:

   ```bash
   gcloud functions describe shakahari-recorder --gen2 --region=us-west1 \
     --format="value(serviceConfig.uri)"
   ```

   Re-run this same `deploy` command any time you change `src/recorder.py`
   or `env.yaml` — environment variables are baked in at deploy time, they
   don't hot-reload.

5. **Register the webhook with Telegram:**

   ```bash
   curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
     -d "url=${CLOUD_FUNCTION_URL}" \
     -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
   ```

6. **Verify it's registered:**

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

Care happens by action, not by plant — you pick up the watering can once and
work through everything that needs it. The digest is shaped to match, grouped
by action with the most overdue group first, so one action can be completed in
a single pass:

> 🌿 **Plant Care Tasks (2026-09-19)**  
> _Warm and dry — watering is running ahead of schedule._
>
> 💧 **WATER** · 3 plants  
> 🔴 **Monstera** — 12d · 🔁10d→8d (high ET₀)  
> 🟡 **Peace Lily** — 15d · 🔁14d  
> 🟢 **Black Pagoda** — 11d · 🔁10d→8d (high ET₀)
>
> 🧪 **FERTILIZE** · 4 plants  
> &nbsp;&nbsp;🍊 **Espoma Citrus-tone**  
> 🔴 **Avocado** — never · 🔁120d  
> &nbsp;&nbsp;🌸 **Miracle-Gro Bloom Booster**  
> 🔴 **Bougainvillea** — 24d · 🔁10d  
> 🟡 **Geranium** — 12d · 🔁10d  
> &nbsp;&nbsp;❓ **Not set**  
> 🟢 **Mint** — never · 🔁14d

Each line shows how long it has been (`12d`, or `never`) and the interval that
applies (`🔁10d`). When weather or season moved that interval, the line shows
the change and why: `🔁10d→8d (high ET₀)`.

**Fertilizing is subdivided by product.** Plants using the same bottle are
grouped together — one trip to one shelf — with the dilution annotated per
plant where it differs (`½ strength`). A plant with no `Fertilizer` value
lands in a visible **❓ Not set** group, always sorted last so a
misconfiguration never buries real work.

### How recommendations are decided

Intervals are computed per plant, per action, then the *same numbers* are given
to Gemini and enforced afterwards — so the model and the safety net cannot
disagree. (Previously the prompt got prose weather while the filter applied
fixed constants, silently overriding whatever the model concluded.)

What moves an interval:

| Signal | Effect |
|--------|--------|
| **Evapotranspiration (ET₀)** | The core watering driver — it already folds in heat, humidity, sun and wind. Scales the interval inversely, clamped to ±40%. Damped for `established` plantings, whose deep roots buffer a hot week in a way a pot cannot. |
| **Rain, past and forecast** | Recent rain defers outdoor watering; *incoming* rain defers it too, and defers outdoor feeding (it would wash off before uptake). Indoor plants ignore rain entirely. |
| **Humidity** | Above 60% RH misting is dropped altogether rather than merely stretched — it achieves nothing. Very dry air shortens watering slightly. |
| **Season** | Taken from `daylight_duration`, not a hardcoded month table, so it stays correct anywhere. Feeding is **suppressed entirely in dormancy** (≈ Nov–Feb in LA) and stretched in shoulder season. |
| **Fertilizer product** | Each product carries its own cadence: bloom booster every 10d, acid feed every 35d, succulents every 120d. |
| **Irrigation** | `sprinkler`/`drip` suppress watering and misting; in-ground plantings suppress rotate, repot and move. |
| **Heat spike** | `MOVE` is triggered by a forecast above 35°C on an outdoor pot, rather than being a recurring chore. |

Two rules keep the digest from filling with things you would never act on:

- **`PRUNE` and `REPOT` are condition-driven.** "Never repotted" is the normal
  state of a plant, not a backlog, so they are never proposed merely because no
  log entry exists. Spacing is still enforced once they *have* been done.
- **`CHECK` is a fallback, not an extra.** If you are already at the plant to
  water or feed it, you are looking at it — so `CHECK` only earns a line for
  plants nothing else brings you to.

Whatever the modifiers do, every interval is clamped to a per-action floor and
ceiling (watering can never be recommended more often than every 2 days).

### Previewing without sending

```bash
python scripts/dry_run.py            # build today's digest, print it, send nothing
python scripts/dry_run.py --live     # use the sheet exactly as it is
python scripts/dry_run.py --table    # paste-ready Fertilizer / Watering values
```

Prints the derived climate, every plant's computed intervals (with `✗` for
actions that do not apply), the rendered message and the keyboard. Nothing
reaches the Sheet or Telegram.

### Interacting with the Bot

Every task in the daily digest has its own named button:

- **Tap a task's button** (e.g. "💧 Water Monstera") to log it instantly —
  the button changes to show exactly what was logged and when (e.g.
  "✓ Water Monstera — 2026-08-20"), and a toast confirms it. Nothing new is
  added to the chat, so you never lose your scroll position.
- **Tap "Mark watering complete"** (or rotating / etc. — one button per action
  type actually in today's digest) to confirm every plant currently needing
  that action in one tap.
- **For fertilizing, there is one button per product** ("🍊 Mark Espoma
  Citrus-tone done"), never a single button for the action. A bulk tap has to
  mean one real-world act with one bottle — a combined button would claim the
  azalea's acid feed and the bougainvillea's bloom booster at the same time.
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
│   ├── actions.py       # Shared action constants (icons, gerunds, care types)
│   ├── agent.py         # Gemini prompt + the filter that enforces the intervals
│   ├── callbacks.py     # Telegram callback_data encode/decode
│   ├── config.py        # Configuration & Env Vars
│   ├── digest.py        # Grouping and rendering of the daily message
│   ├── fertilizers.py   # Fertilizer product registry + sheet-value normalization
│   ├── intervals.py     # Context-aware care intervals (pure, no I/O)
│   ├── plant_api.py     # Perenual API + Gemini-grounded care lookups
│   ├── storage.py       # Google Sheets DB & Care Logging
│   ├── telegram_bot.py  # Notification Service
│   ├── recorder.py      # Cloud Function for Real-Time Logging
│   └── weather.py       # Open-Meteo fetch + derived climate signals
├── scripts/
│   └── dry_run.py       # Preview the digest (and the sheet table) without sending
├── data/
│   └── fertilizer.md    # Source notes behind the product assignments
├── tests/               # pytest suite
├── main.py              # Entry point (Advisor cron job)
└── requirements.txt     # Python dependencies
```

## 🤝 Contributing

Feel free to fork this project and add features like:

- Photo analysis (upload a photo to check for pests).
- Hardware integration (ESP32 soil sensors).

## 📄 License

MIT License. Free to use and modify.
