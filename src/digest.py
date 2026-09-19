"""Digest rendering: group by action, sub-divide fertilizing by product.

Care happens by action, not by plant -- you pick up the watering can once and
work through everything that needs it. The digest is shaped to match that, so
one action can be completed in a single pass instead of being scanned out of a
plant-ordered list.

Fertilizing is subdivided further, by bottle: a bulk "done" tap has to mean one
real-world act with one product, not a claim that four different fertilizers
were applied at once.
"""

from datetime import datetime

from src.actions import ACTION_ICONS, ACTION_GERUNDS, CARE_ACTIONS
from src.callbacks import encode_task_button, encode_alldone, encode_action_done, encode_fert_done
from src.fertilizers import product_of, strength_of, icon_of

PRIORITY_MARKERS = {
    'HIGH': '🔴',
    'MEDIUM': '🟡',
    'LOW': '🟢',
}

NOT_SET_HEADING = "❓ Not set"

# Groups sort ascending on negated overdue ratio, so +inf lands last: an
# unassigned plant stays visible but never outranks work that can be done.
_LAST = float("inf")


def _overdue_ratio(task):
    """How far past due, as a multiple of the plant's own threshold.

    Comparing ratios rather than raw days keeps a 3-day-overdue misting from
    outranking a 30-day-overdue feeding."""
    days = task.get('days_since')
    if days is None:
        return float("inf")          # never done ranks as maximally overdue
    threshold = task.get('threshold') or 1
    return days / threshold


def _action_of(task):
    return (task.get('action') or 'CHECK').upper()


def _fert_code(task):
    return task.get('fertilizer')


def _group_tasks(tasks):
    """[(action, [task, ...]), ...] ordered by the most overdue member."""
    groups = {}
    for t in tasks:
        groups.setdefault(_action_of(t), []).append(t)

    def order(item):
        action, members = item
        tie = CARE_ACTIONS.index(action) if action in CARE_ACTIONS else len(CARE_ACTIONS)
        return (-max(_overdue_ratio(t) for t in members), tie)

    ordered = sorted(groups.items(), key=order)
    return [(action, sorted(members, key=_overdue_ratio, reverse=True))
            for action, members in ordered]


def _subgroup_fertilizer(members):
    """[(product_label, icon, [task, ...]), ...] -- one entry per bottle.

    The three all-purpose dilutions share a product, so they collapse into a
    single heading; the dilution is annotated on each plant's line instead.
    Unmapped plants land in a visible 'Not set' group, sorted last."""
    buckets = {}
    for t in members:
        code = _fert_code(t)
        label = product_of(code) or NOT_SET_HEADING
        buckets.setdefault(label, {"icon": icon_of(code) or "❓", "tasks": []})
        buckets[label]["tasks"].append(t)

    def order(item):
        label, bucket = item
        if label == NOT_SET_HEADING:
            return (_LAST, label)
        return (-max(_overdue_ratio(t) for t in bucket["tasks"]), label)

    return [(label, bucket["icon"], sorted(bucket["tasks"], key=_overdue_ratio, reverse=True))
            for label, bucket in sorted(buckets.items(), key=order)]


def _since_code(task):
    days = task.get('days_since')
    return "never" if days is None else f"{days}d"


def _threshold_code(task):
    """'🔁10d', or '🔁10d→8d (high ET₀)' when the weather moved it."""
    threshold = task.get('threshold')
    if not threshold:
        return ""

    base = task.get('base')
    adjustments = task.get('adjustments') or []

    if base and base != threshold and adjustments:
        labels = ", ".join(label for label, _ in adjustments)
        return f"🔁{base}d→{threshold}d ({labels})"
    return f"🔁{threshold}d"


def _task_line(task, annotate_strength=False):
    marker = PRIORITY_MARKERS.get((task.get('priority') or '').upper(), '')
    name = task.get('name', 'Unknown')

    parts = [f"{marker} <b>{name}</b>"]

    if annotate_strength:
        strength = strength_of(_fert_code(task))
        if strength:
            parts.append(f"<i>{strength}</i>")

    tail = _since_code(task)
    threshold = _threshold_code(task)
    if threshold:
        tail = f"{tail} · {threshold}"

    return f"{' '.join(parts)} — {tail}"


def format_digest(tasks, summary):
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🌿 <b>Plant Care Tasks ({today})</b>"]
    if summary:
        lines.append(f"<i>{summary}</i>")

    for action, members in _group_tasks(tasks):
        icon = ACTION_ICONS.get(action, '📋')
        noun = "plant" if len(members) == 1 else "plants"
        lines.append("")
        lines.append(f"{icon} <b>{action}</b> · {len(members)} {noun}")

        if action == "FERTILIZE":
            for label, fert_icon, bucket in _subgroup_fertilizer(members):
                lines.append(f"  {fert_icon} <b>{label}</b>")
                lines.extend(_task_line(t, annotate_strength=True) for t in bucket)
        else:
            lines.extend(_task_line(t) for t in members)

    return "\n".join(lines)


def build_keyboard(tasks):
    """One named button per task, then the bulk confirmations.

    Bulk fertilizing is per product code rather than one button for the action:
    the codes differ by dilution, so confirming the half-strength plants must
    not also claim the full-strength ones."""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = []

    for action, members in _group_tasks(tasks):
        for t in members:
            icon = ACTION_ICONS.get(action, '📋')
            name = t.get('name', 'Unknown')
            rows.append([{
                "text": f"{icon} {action.title()} {name}",
                "callback_data": encode_task_button(action, name),
            }])

        if action == "FERTILIZE":
            seen = []
            for t in members:
                code = _fert_code(t)
                if code and code not in seen:
                    seen.append(code)
            for code in seen:
                rows.append([{
                    "text": f"{icon_of(code)} Mark {product_of(code)} done",
                    "callback_data": encode_fert_done(code, today),
                }])
        else:
            icon = ACTION_ICONS.get(action, '📋')
            gerund = ACTION_GERUNDS.get(action, action.lower())
            rows.append([{
                "text": f"{icon} Mark {gerund} complete",
                "callback_data": encode_action_done(action, today),
            }])

    rows.append([{"text": "✅ Mark everything above done", "callback_data": encode_alldone(today)}])
    return {"inline_keyboard": rows}
