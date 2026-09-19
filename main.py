from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_message
from src.digest import format_digest, build_keyboard
from src.recorder import telegram_webhook  # noqa: F401 -- Cloud Function entry point, unused by the Advisor


def main():
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
    care_history = db.get_history_summary(limit_per_plant=5)

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
