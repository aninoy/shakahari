from datetime import datetime
from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_message
from src.actions import ACTION_ICONS, ACTION_GERUNDS, CARE_ACTIONS
from src.callbacks import encode_task_button, encode_alldone, encode_action_done
from src.recorder import telegram_webhook  # noqa: F401 -- Cloud Function entry point, unused by the Advisor

# Priority indicators
PRIORITY_MARKERS = {
    'HIGH': '🔴',
    'MEDIUM': '🟡',
    'LOW': '🟢',
}


def format_tasks(tasks, summary):
    """Format tasks into a compact digest: one line per task showing a
    deterministic days-since-vs-threshold code instead of Gemini's prose."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🌿 <b>Plant Care Tasks ({today})</b>"]

    if summary:
        lines.append(f"<i>{summary}</i>")

    lines.append("")
    for t in tasks:
        lines.append(_format_task_line(t))

    return "\n".join(lines)


def _format_task_line(t):
    action = t.get('action', 'CHECK').upper()
    icon = ACTION_ICONS.get(action, '📋')
    name = t.get('name', 'Unknown')
    priority = t.get('priority', '').upper()
    marker = PRIORITY_MARKERS.get(priority, '')

    days = t.get('days_since')
    threshold = t.get('threshold')
    if days is None:
        code = "never"
    elif threshold:
        code = f"{days}d≥{threshold}d"
    else:
        code = f"{days}d"

    return f"{marker}{icon} <b>{name}</b> — {code}"


def build_digest_keyboard(tasks):
    """One named button per task, one bulk "Mark X complete" button per action
    type present, plus a final mark-everything row."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []
    present_actions = []
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        name = t.get('name', 'Unknown')
        icon = ACTION_ICONS.get(action, '📋')
        rows.append([
            {"text": f"{icon} {action.title()} {name}", "callback_data": encode_task_button(action, name)},
        ])
        if action not in present_actions:
            present_actions.append(action)

    for action in CARE_ACTIONS:
        if action in present_actions:
            icon = ACTION_ICONS.get(action, '📋')
            gerund = ACTION_GERUNDS.get(action, action.lower())
            rows.append([
                {"text": f"{icon} Mark {gerund} complete", "callback_data": encode_action_done(action, today)},
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
