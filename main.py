"""Shakahari entry points.

This module is loaded by TWO different runtimes:

  * the daily GitHub Actions "Advisor" cron, which calls main()
  * the Google Cloud Function "Recorder", whose entry point is
    telegram_webhook (functions-framework resolves it from here)

The Recorder runs in a small container and needs none of the Advisor's
machinery. Importing the Advisor stack -- the Gemini SDK above all -- at module
level cost ~36MB on every webhook request and pushed the container past its
memory limit, so it was OOM-killed mid-request and no Sheet write ever landed.
The Advisor's imports are therefore deferred into _advisor(), which only the
cron path calls.
"""
from src.recorder import telegram_webhook  # noqa: F401 -- Cloud Function entry point


def _advisor():
    """Import the Advisor-only dependencies. Never reached by the Recorder."""
    from src.config import MODEL_ID
    from src.storage import PlantDB
    from src.weather import get_forecast
    from src.agent import PlantAgent
    from src.telegram_bot import send_message
    from src.digest import format_digest, build_keyboard
    return (MODEL_ID, PlantDB, get_forecast, PlantAgent,
            send_message, format_digest, build_keyboard)


def main():
    (MODEL_ID, PlantDB, get_forecast, PlantAgent,
     send_message, format_digest, build_keyboard) = _advisor()

    print(f"🌿 Starting Plant Care Advisor ({MODEL_ID})...")

    # 1. Connect to the Sheet
    try:
        db = PlantDB()
    except Exception as e:
        print(f"❌ DB Init Failed: {e}")
        return

    # 2. Get Weather Context
    weather = get_forecast()
    if not weather:
        print("⚠️ Continuing without weather data...")

    # 3. Get Care History for context
    care_history = db.get_history_summary()

    # 4. Agent Reasoning
    agent = PlantAgent()
    tasks, summary = agent.get_tasks(weather, db.get_inventory(), care_history)

    # 5. Notify & Update Status
    if tasks:
        message = format_digest(tasks, summary)
        keyboard = build_keyboard(tasks)
        if send_message(message, reply_markup=keyboard):
            db.mark_pending(tasks)
            print(f"✅ Sent {len(tasks)} care recommendations.")
        else:
            # Marking these pending now would hide them from tomorrow's run even
            # though no digest ever reached the phone.
            print(f"❌ Digest failed to send — leaving {len(tasks)} task(s) unmarked for tomorrow's run.")
    else:
        print("✅ No tasks today. All plants healthy!")


if __name__ == "__main__":
    main()
