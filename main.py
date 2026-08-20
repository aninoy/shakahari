from datetime import datetime
from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_message
from src.actions import ACTION_ICONS

# Priority indicators
PRIORITY_MARKERS = {
    'HIGH': '🔴',
    'MEDIUM': '🟡',
    'LOW': '🟢',
}


def format_tasks(tasks, summary):
    """Format tasks into a readable Telegram message grouped by action type."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🌿 <b>Plant Care Tasks ({today})</b>"]
    
    if summary:
        lines.append(f"<i>{summary}</i>")
    
    # Group tasks by action type
    by_action = {}
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        if action not in by_action:
            by_action[action] = []
        by_action[action].append(t)
    
    # Quick summary section - grouped by action
    lines.append("")
    for action in ['WATER', 'FERTILIZE', 'MIST', 'ROTATE', 'MOVE', 'PRUNE', 'REPOT', 'CHECK']:
        if action in by_action:
            icon = ACTION_ICONS.get(action, '📋')
            plant_names = [t.get('name', '?') for t in by_action[action]]
            lines.append(f"{icon} <b>{action}</b>: {', '.join(plant_names)}")
    
    # Detailed section with reasons and clickable commands
    lines.append("\n—")
    lines.append("<b>Details:</b>")
    for t in tasks:
        action = t.get('action', 'CHECK').upper()
        icon = ACTION_ICONS.get(action, '📋')
        name = t.get('name', 'Unknown')
        reason = t.get('reason', '')
        priority = t.get('priority', '').upper()
        priority_marker = PRIORITY_MARKERS.get(priority, '')
        
        # Create clickable command (e.g. /water_monstera)
        safe_name = "".join(c if c.isalnum() else "_" for c in name.lower())
        safe_name = "_".join(filter(None, safe_name.split("_"))) # Remove duplicate underscores
        command = f"/{action.lower()}_{safe_name}"
        
        lines.append(f"{priority_marker}{icon} <b>{name}</b>: {reason}")
        lines.append(f"   👉 Tap to log: {command}")
    
    lines.append("\n<i>Reply 'Done' to confirm all at once.</i>")
    
    return "\n".join(lines)


def main():
    print(f"🌿 Starting Plant Care Advisor ({MODEL_ID})...")

    # 1. Sync Mailbox (process user replies)
    try:
        db = PlantDB()
        db.sync_from_mailbox()
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

    # 4. Notify & Update Status
    if tasks:
        message = format_tasks(tasks, summary)
        send_message(message)
        db.mark_pending(tasks)
        print(f"✅ Sent {len(tasks)} care recommendations.")
    else:
        print("✅ No tasks today. All plants healthy!")


if __name__ == "__main__":
    main()