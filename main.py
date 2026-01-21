from datetime import datetime
from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_alert

# Action icons for Telegram messages
ACTION_ICONS = {
    'WATER': '💧',
    'FERTILIZE': '🧪',
    'MIST': '💨',
    'ROTATE': '🔄',
    'MOVE': '📍',
    'PRUNE': '✂️',
    'REPOT': '🪴',
    'CHECK': '🔍',
}

# Priority indicators
PRIORITY_MARKERS = {
    'HIGH': '🔴',
    'MEDIUM': '🟡',
    'LOW': '🟢',
}


def format_tasks(tasks, summary):
    """Format tasks into a readable Telegram message."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🌿 *Plant Care Tasks ({today})*"]
    
    if summary:
        lines.append(f"_{summary}_\n")
    
    # Group tasks by priority
    by_priority = {'HIGH': [], 'MEDIUM': [], 'LOW': []}
    for t in tasks:
        priority = t.get('priority', 'MEDIUM').upper()
        if priority not in by_priority:
            priority = 'MEDIUM'
        by_priority[priority].append(t)
    
    # Output in priority order
    for priority in ['HIGH', 'MEDIUM', 'LOW']:
        if by_priority[priority]:
            marker = PRIORITY_MARKERS.get(priority, '')
            lines.append(f"\n{marker} *{priority} Priority*")
            
            for t in by_priority[priority]:
                action = t.get('action', 'CHECK').upper()
                icon = ACTION_ICONS.get(action, '📋')
                name = t.get('name', 'Unknown')
                reason = t.get('reason', '')
                lines.append(f"  {icon} *{name}*: {reason}")
    
    lines.append("\n_Reply 'Done' to confirm all._")
    lines.append("_Or '[Action] [Plant]' for specific updates._")
    lines.append("_e.g., 'Watered Fern' or 'Rotated Monstera'_")
    
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
        send_alert(message)
        db.mark_pending(tasks)
        print(f"✅ Sent {len(tasks)} care recommendations.")
    else:
        print("✅ No tasks today. All plants healthy!")


if __name__ == "__main__":
    main()