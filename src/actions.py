"""Shared care-action constants used by the Advisor, the agent, and the Recorder."""

CARE_ACTIONS = [
    "WATER",
    "FERTILIZE",
    "MIST",
    "ROTATE",
    "MOVE",
    "PRUNE",
    "REPOT",
    "CHECK",
]

ACTION_ICONS = {
    "WATER": "💧",
    "FERTILIZE": "🧪",
    "MIST": "💨",
    "ROTATE": "🔄",
    "MOVE": "📍",
    "PRUNE": "✂️",
    "REPOT": "🪴",
    "CHECK": "🔍",
}

# Gerunds for bulk "Mark X complete" digest buttons.
ACTION_GERUNDS = {
    "WATER": "watering",
    "FERTILIZE": "fertilizing",
    "MIST": "misting",
    "ROTATE": "rotating",
    "MOVE": "moving",
    "PRUNE": "pruning",
    "REPOT": "repotting",
    "CHECK": "checking",
}
