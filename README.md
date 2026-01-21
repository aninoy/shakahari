# 🌱 Shakahari

**Shakahari** is a serverless, agent-driven plant care system that runs for **$0/month**.

Unlike dumb timer apps, Shakahari uses **Gemini 2.5 Flash** (AI), **Open-Meteo** (Weather), and **Google Sheets** (Memory) to intelligently manage the watering and fertilization schedules for your entire garden. It adjusts automatically for rain, heatwaves, seasons, and plant types.

## ✨ Features

- **🧠 Context-Aware Agent:** Shakahari analyzes recent rain history, temperature forecasts, and specific plant hardiness to decide if care is _actually_ needed.
- **🌦️ Weather Integrated:** Automatically skips watering outdoor plants if it rained heavily yesterday or is about to rain today.
- **💬 Two-Way Feedback:** Receive tasks via **Telegram**. Reply with "Done", "Watered Fern", or "Fertilized Monstera" to automatically update the database.
- **⚡ Rate-Limit Proof:** Uses architectural batching to check your entire inventory in a single API call.
- **📂 Serverless:** Runs on a scheduled GitHub Action (Cron). No AWS/GCP bills. No server maintenance.

## 🏗️ Architecture

```mermaid
graph TD;
    A[GitHub Action (Daily Trigger)] -->|1. Wake Up| B(Main Script)
    B -->|2. Check Mailbox| C{Telegram API}
    C -->|User Replies| D[Update Google Sheet]
    B -->|3. Get Context| E[Open-Meteo Weather]
    B -->|4. Get Inventory| F[Google Sheets DB]
    B -->|5. Ask Agent| G[Gemini 2.5 Flash]
    G -->|6. Decisions| H{Tasks Needed?}
    H -->|Yes| I[Send Telegram Alert]
    H -->|No| J[Sleep]
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

   | Name | Type | Location | Notes | Last Watered | Last Fertilized | Status |
   |------|------|----------|-------|--------------|-----------------|--------|

4. **Important:** Create a **Service Account** in Google Cloud Console, download the JSON key, and **share** your Google Sheet with the service account's email address (Editor access).

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

## 📱 Usage Guide

### The Daily Notification

Every morning, if action is required, Shakahari sends you a digest:

> 🌿 **Care Tasks (2026-01-20)**
>
> 💧 Fiddle Leaf Fig: Soil likely dry after 7 days; indoor heat is high.
>
> 🧪 Monstera: It is growing season and hasn't been fed in 4 weeks.
>
> _Reply 'Done' to confirm._

### Interacting with the Bot

You don't need to open the spreadsheet. Just reply to the bot:

- **"Done"** or **"Done all"**: Marks all pending tasks (Water & Fertilizer) as completed today.
- **"Watered [Plant Name]"**: Updates only the _Last Watered_ date for that specific plant.
- **"Fertilized [Plant Name]"**: Updates only the _Last Fertilized_ date for that specific plant.

> **Note:** Shakahari processes your replies the **next time** it runs (the following morning).

## 📂 Project Structure

```
/
├── .github/workflows/   # Cron schedule configuration
├── src/
│   ├── agent.py         # Gemini AI Logic (Prompt Engineering)
│   ├── config.py        # Configuration & Env Vars
│   ├── storage.py       # Google Sheets & Mailbox Logic
│   ├── telegram_bot.py  # Notification Service
│   └── weather.py       # Open-Meteo Integration
├── main.py              # Entry point
└── requirements.txt     # Python dependencies
```

## 🤝 Contributing

Feel free to fork this project and add features like:

- Photo analysis (upload a photo to check for pests).
- Hardware integration (ESP32 soil sensors).

## 📄 License

MIT License. Free to use and modify.