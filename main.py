from datetime import datetime
from src.config import MODEL_ID
from src.storage import PlantDB
from src.weather import get_forecast
from src.agent import PlantAgent
from src.telegram_bot import send_alert

def main():
    print(f"🌿 Starting Plant Agent ({MODEL_ID})...")

    # 1. Sync Mailbox (Did you fertilize yesterday?)
    try:
        db = PlantDB()
        db.sync_from_mailbox() 
    except Exception as e:
        print(f"❌ DB Init Failed: {e}")
        return

    # 2. Get Weather
    weather = get_forecast()
    if not weather: return

    # 3. Agent Reasoning
    agent = PlantAgent()
    tasks = agent.get_tasks(weather, db.get_inventory())

    # 4. Notify & Update Status
    if tasks:
        today = datetime.now().strftime("%Y-%m-%d")
        msg = [f"🌿 *Care Tasks ({today})*"]
        
        for t in tasks:
            icon = "💧" if t['action'] == "WATER" else "🧪"
            if t['action'] == "BOTH": icon = "💧+🧪"
            
            msg.append(f"{icon} *{t['name']}*: {t['reason']}")

        msg.append("\n_Reply 'Done' to confirm all._")
        msg.append("_Or 'Fertilized [Name]' for specific updates._")
        
        send_alert("\n".join(msg))
        db.mark_pending(tasks)
        print(f"✅ Sent alerts for {len(tasks)} plants.")
    else:
        print("✅ No tasks today.")

if __name__ == "__main__":
    main()