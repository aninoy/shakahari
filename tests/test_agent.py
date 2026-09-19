import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.agent import PlantAgent

CARE = {"min_watering_days": 5, "max_watering_days": 10, "watering": "Average"}


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


@pytest.fixture(autouse=True)
def _stub_care(monkeypatch):
    monkeypatch.setattr("src.agent.get_care_guidelines", lambda name: dict(CARE))


def days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def row(name="Monstera", **overrides):
    base = {
        "Name": name, "Last Watered": "", "Last Fertilized": "",
        "Environment": "indoor", "Fertilizer": "ALLPURPOSE", "Watering": "manual",
    }
    base.update(overrides)
    return base


def prompt_of(agent):
    return agent.client.models.generate_content.call_args.kwargs["contents"]


# --- enrichment -----------------------------------------------------------

def test_water_tasks_carry_days_since_and_the_computed_threshold():
    agent = make_agent([{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"}])
    df = pd.DataFrame([row("Monstera", **{"Last Watered": days_ago(12)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert tasks[0]["days_since"] == 12
    assert tasks[0]["threshold"] == 10      # no weather -> base interval
    assert tasks[0]["base"] == 10


def test_non_water_actions_get_their_own_computed_threshold():
    agent = make_agent([{"name": "Pothos", "action": "ROTATE", "priority": "LOW", "reason": "leaning"}])
    df = pd.DataFrame([row("Pothos")])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert tasks[0]["days_since"] is None
    assert tasks[0]["threshold"] == 7


def test_fertilize_threshold_comes_from_the_plants_product():
    """Replaces the flat MIN_ACTION_INTERVALS['FERTILIZE'] == 14 for everything."""
    agent = make_agent([{"name": "Snake Plant", "action": "FERTILIZE", "priority": "LOW", "reason": "due"}])
    df = pd.DataFrame([row("Snake Plant", Fertilizer="SUCCULENT", **{"Last Fertilized": days_ago(200)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert tasks[0]["threshold"] == 120
    assert tasks[0]["fertilizer"] == "SUCCULENT"


def test_tasks_carry_the_adjustments_the_digest_renders():
    agent = make_agent([{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"}])
    df = pd.DataFrame([row("Monstera", **{"Last Watered": days_ago(30)})])
    hot = {
        "time": [days_ago(3), days_ago(2), days_ago(1),
                 datetime.now().strftime("%Y-%m-%d")],
        "et0_fao_evapotranspiration": [6.6, 6.6, 6.6, 6.6],
        "precipitation_sum": [0, 0, 0, 0],
        "relative_humidity_2m_mean": [50, 50, 50, 50],
        "temperature_2m_max": [30, 30, 30, 30],
        "daylight_duration": [13 * 3600] * 4,
    }

    tasks, _ = agent.get_tasks(weather=hot, inventory_df=df)

    assert tasks[0]["threshold"] < tasks[0]["base"]
    assert tasks[0]["adjustments"], "expected a labelled adjustment"


# --- the post-filter now agrees with the prompt ---------------------------

def test_an_action_done_too_recently_is_filtered_out():
    agent = make_agent([{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"}])
    df = pd.DataFrame([row("Monstera", **{"Last Watered": days_ago(2)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert tasks == []


def test_an_action_past_its_computed_threshold_survives():
    agent = make_agent([{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"}])
    df = pd.DataFrame([row("Monstera", **{"Last Watered": days_ago(11)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert len(tasks) == 1


def test_a_suppressed_action_is_dropped_even_if_the_model_proposes_it():
    """An irrigated plant must never surface a watering task, whatever Gemini says."""
    agent = make_agent([{"name": "Azalea", "action": "WATER", "priority": "HIGH", "reason": "looks dry"}])
    df = pd.DataFrame([row("Azalea", Environment="outdoor", Watering="sprinkler",
                           **{"Last Watered": days_ago(400)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert tasks == []


def test_a_plant_the_model_invented_is_dropped():
    agent = make_agent([{"name": "Ghost Fern", "action": "WATER", "priority": "HIGH", "reason": "?"}])
    df = pd.DataFrame([row("Monstera")])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert tasks == []


# --- prompt content -------------------------------------------------------

def test_the_prompt_carries_the_same_intervals_the_filter_enforces():
    """The root bug: the model used to reason over prose weather while the
    filter applied constants, so its weather judgement was silently overridden."""
    agent = make_agent([])
    df = pd.DataFrame([row("Snake Plant", Fertilizer="SUCCULENT")])

    agent.get_tasks(weather=None, inventory_df=df)

    assert "120" in prompt_of(agent)


def test_suppressed_actions_are_not_offered_to_the_model():
    agent = make_agent([])
    df = pd.DataFrame([row("Azalea", Environment="outdoor", Watering="sprinkler")])

    agent.get_tasks(weather=None, inventory_df=df)

    prompt = prompt_of(agent)
    # The inventory array sits between its heading blurb and the instructions.
    body = prompt[prompt.index("is watered."):prompt.index("## Instructions")]
    plant_block = json.loads(body[body.index("["):body.rindex("]") + 1])

    assert "WATER" not in plant_block[0]["due_in_days"]
    assert "MIST" not in plant_block[0]["due_in_days"]
    assert "FERTILIZE" in plant_block[0]["due_in_days"]


def test_a_gemini_failure_returns_no_tasks_rather_than_raising():
    agent = PlantAgent.__new__(PlantAgent)
    agent.client = MagicMock()
    agent.client.models.generate_content.side_effect = RuntimeError("API down")

    tasks, summary = agent.get_tasks(weather=None, inventory_df=pd.DataFrame([row()]))

    assert tasks == []
    assert summary == ""


def test_a_sheet_without_the_new_columns_still_runs():
    """Degrades to '❓ Not set' and manual watering rather than breaking."""
    agent = make_agent([{"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"}])
    df = pd.DataFrame([{
        "Name": "Monstera", "Last Watered": days_ago(12),
        "Last Fertilized": "", "Environment": "indoor",
    }])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert len(tasks) == 1
    assert tasks[0]["fertilizer"] is None


# --- CHECK is the fallback action, not an extra one -----------------------

def test_check_is_dropped_when_the_plant_already_has_real_work_due():
    """If you are already at the plant watering it, you are checking it. CHECK
    exists for plants you would otherwise not touch."""
    agent = make_agent([
        {"name": "Monstera", "action": "WATER", "priority": "HIGH", "reason": "dry"},
        {"name": "Monstera", "action": "CHECK", "priority": "LOW", "reason": "routine"},
    ])
    df = pd.DataFrame([row("Monstera", **{"Last Watered": days_ago(40)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    actions = [t["action"] for t in tasks]
    assert "WATER" in actions
    assert "CHECK" not in actions


def test_check_survives_for_a_plant_with_nothing_else_due():
    agent = make_agent([{"name": "Azalea", "action": "CHECK", "priority": "LOW", "reason": "routine"}])
    df = pd.DataFrame([row("Azalea", Environment="outdoor", Watering="sprinkler",
                           **{"Last Fertilized": days_ago(1)})])

    tasks, _ = agent.get_tasks(weather=None, inventory_df=df)

    assert [t["action"] for t in tasks] == ["CHECK"]


def test_check_is_not_offered_to_the_model_when_other_work_is_due():
    agent = make_agent([])
    df = pd.DataFrame([row("Monstera", **{"Last Watered": days_ago(40)})])

    agent.get_tasks(weather=None, inventory_df=df)

    prompt = prompt_of(agent)
    body = prompt[prompt.index("is watered."):prompt.index("## Instructions")]
    block = json.loads(body[body.index("["):body.rindex("]") + 1])

    assert "CHECK" not in block[0]["due_in_days"]
    assert "WATER" in block[0]["due_in_days"]
