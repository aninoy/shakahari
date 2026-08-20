from datetime import datetime

from main import format_tasks, build_digest_keyboard


def test_format_tasks_has_no_tap_to_log_text():
    tasks = [{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "Soil dry"}]

    text = format_tasks(tasks, "All good")

    assert "Tap to log" not in text
    assert "/water_monstera" not in text
    assert "Monstera" in text
    assert "Soil dry" in text


def test_build_digest_keyboard_has_one_row_per_task_plus_mark_all_done():
    tasks = [
        {"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "Soil dry"},
        {"name": "Pothos", "action": "ROTATE", "priority": "LOW", "reason": "Leaning"},
    ]

    keyboard = build_digest_keyboard(tasks)
    rows = keyboard["inline_keyboard"]

    assert len(rows) == 3
    assert rows[0][0] == {"text": "💧 Watered", "callback_data": "t:WATER:Monstera"}
    assert rows[0][1] == {"text": "⏭ Skip today", "callback_data": "skip:WATER:Monstera"}
    assert rows[1][0] == {"text": "🔄 Rotated", "callback_data": "t:ROTATE:Pothos"}
    today = datetime.now().strftime("%Y-%m-%d")
    assert rows[2] == [{"text": "✅ Mark everything above done", "callback_data": f"alldone:{today}"}]
