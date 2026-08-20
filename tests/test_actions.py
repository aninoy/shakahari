from src.actions import CARE_ACTIONS, ACTION_ICONS, ACTION_GERUNDS


def test_care_actions_has_all_eight_action_types():
    assert CARE_ACTIONS == [
        "WATER", "FERTILIZE", "MIST", "ROTATE", "MOVE", "PRUNE", "REPOT", "CHECK",
    ]


def test_action_icons_covers_every_care_action():
    for action in CARE_ACTIONS:
        assert action in ACTION_ICONS


def test_action_gerunds_covers_every_care_action():
    for action in CARE_ACTIONS:
        assert action in ACTION_GERUNDS
