"""Encode/decode Telegram callback_data for digest buttons and the /log flow.

Plant names are embedded directly (no substring matching, no ID lookup) —
this is what makes plant matching exact instead of fuzzy. Assumes plant
names never contain ':' (documented limitation, see design spec).
"""


def encode_task_button(action, plant_name):
    return f"t:{action}:{plant_name}"


def encode_skip_button(action, plant_name):
    return f"skip:{action}:{plant_name}"


def encode_alldone(date):
    return f"alldone:{date}"


def encode_log_select(plant_name):
    return f"logsel:{plant_name}"


def encode_log_action(plant_name, action):
    return f"logact:{plant_name}:{action}"


def encode_log_back():
    return "logback"


def decode_callback(data):
    parts = data.split(":")
    kind = parts[0] if parts else ""

    if kind == "t" and len(parts) == 3:
        return {"kind": "task", "action": parts[1], "plant": parts[2]}
    if kind == "skip" and len(parts) == 3:
        return {"kind": "skip", "action": parts[1], "plant": parts[2]}
    if kind == "alldone" and len(parts) == 2:
        return {"kind": "alldone", "date": parts[1]}
    if kind == "logsel" and len(parts) == 2:
        return {"kind": "logsel", "plant": parts[1]}
    if kind == "logact" and len(parts) == 3:
        return {"kind": "logact", "plant": parts[1], "action": parts[2]}
    if kind == "logback" and len(parts) == 1:
        return {"kind": "logback"}
    if kind == "noop" and len(parts) == 1:
        return {"kind": "noop"}

    return {"kind": "unknown"}
