import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd

from src.agent import PlantAgent


class FakeResponse:
    def __init__(self, text):
        self.text = text


def make_agent(gemini_tasks, summary="All good"):
    """Builds a PlantAgent without hitting the real Gemini client."""
    agent = PlantAgent.__new__(PlantAgent)
    agent.client = MagicMock()
    agent.client.models.generate_content.return_value = FakeResponse(
        json.dumps({"tasks": gemini_tasks, "summary": summary})
    )
    return agent


def test_get_tasks_enriches_water_with_days_since_and_watering_max_days(monkeypatch):
    monkeypatch.setattr("src.agent.get_care_guidelines", lambda name: {
        "min_watering_days": 5, "max_watering_days": 10, "watering": "Average",
    })
    agent = make_agent([{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"}])

    last_watered = (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d")
    inventory_df = pd.DataFrame([
        {"Name": "Monstera", "Last Watered": last_watered, "Last Fertilized": "", "Environment": "indoor"},
    ])

    tasks, summary = agent.get_tasks(weather=None, inventory_df=inventory_df)

    assert len(tasks) == 1
    assert tasks[0]["days_since"] == 12
    assert tasks[0]["threshold"] == 10


def test_get_tasks_uses_min_action_interval_as_threshold_for_non_water_actions(monkeypatch):
    monkeypatch.setattr("src.agent.get_care_guidelines", lambda name: {
        "min_watering_days": 5, "max_watering_days": 10, "watering": "Average",
    })
    agent = make_agent([{"name": "Pothos", "action": "ROTATE", "priority": "LOW", "reason": "leaning"}])

    inventory_df = pd.DataFrame([
        {"Name": "Pothos", "Last Watered": "", "Last Fertilized": "", "Environment": "indoor"},
    ])

    tasks, summary = agent.get_tasks(weather=None, inventory_df=inventory_df)

    assert tasks[0]["days_since"] is None  # no CareHistory passed in for ROTATE
    assert tasks[0]["threshold"] == 7  # MIN_ACTION_INTERVALS["ROTATE"]
