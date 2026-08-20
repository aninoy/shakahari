from datetime import datetime
from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_message
from src.actions import ACTION_ICONS
from src.callbacks import encode_task_button, encode_skip_button, encode_alldone
from src.recorder import telegram_webhook  # noqa: F401 -- Cloud Function entry point, unused by the Advisor

# Priority indicators
PRIORITY_MARKERS = {
    'HIGH': '🔴',
    'MEDIUM': '🟡',
    'LOW': '🟢',
}

# Past-tense labels for digest confirmation buttons
ACTION_PAST_TENSE = {
    'WATER': 'Watered',
    'FERTILIZE': 'Fertilized',
    'MIST': 'Misted',
    'ROTATE': 'Rotated',
    'MOVE': 'Moved',
    'PRUNE': 'Pruned',
    'REPOT': 'Repotted',
    'CHECK': 'Checked',
}


def format_tasks(tasks, summary):
    """Format tasks into a readable Telegram message grouped by action type."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🌿 <b>Plant Care Tasks ({today})</b>"]

    if summary:
        lines.append(f"<i>{summary}</i>")

    by_action = {}
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        if action not in by_action:
            by_action[action] = []
        by_action[action].append(t)

    lines.append("")
    for action in ['WATER', 'FERTILIZE', 'MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
        if action in by_action:
            icon = ACTION_ICONS.get(action, '📋')
            plant_names = [t.get('name', '?') for t in by_action[action]]
            lines.append(f"{icon} <b>{action}</b>: {', '.join(plant_names)}")

    lines.append("\n—")
    lines.append("<b>Details:</b>")
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        icon = ACTION_ICONS.get(action, '📋')
        name = t.get('name', 'Unknown')
        reason = t.get('reason', '')
        priority = t.get('priority', '').upper()
        priority_marker = PRIORITY_MARKERS.get(priority, '')
        lines.append(f"{priority_marker}{icon} <b>{name}</b>: {reason}")

    return "\n".join(lines)


def build_digest_keyboard(tasks):
    """Builds one button row per task (confirm / skip) plus a final mark-all-done row."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        name = t.get('name', 'Unknown')
        icon = ACTION_ICONS.get(action, '📋')
        label = ACTION_PAST_TENSE.get(action, action.title())
        rows.append([
            {"text": f"{icon} {label}", "callback_data": encode_task_button(action, name)},
            {"text": "⏭ Skip today", "callback_data": encode_skip_button(action, name)},
        ])
    rows.append([{"text": "✅ Mark everything above done", "callback_data": encode_alldone(today)}])
    return {"inline_keyboard": rows}


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
        message = format_tasks(tasks, summary)
        keyboard = build_digest_keyboard(tasks)
        send_message(message, reply_markup=keyboard)
        db.mark_pending(tasks)
        print(f"✅ Sent {len(tasks)} care recommendations.")
    else:
        print("✅ No tasks today. All plants healthy!")


if __name__ == "__main__":
    main()
