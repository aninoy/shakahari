"""Preview the digest without sending it.

Two things live here:

  --table     print the Fertilizer / Watering values to paste into the sheet
  (default)   build today's digest from the live sheet and live weather and
              print the message and keyboard to stdout

Both read one PLANNED mapping, so what gets previewed and what gets pasted
cannot drift apart. Once the sheet carries the columns, run with --live to
preview what it will actually produce.

Nothing in this file writes to the Sheet or to Telegram.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.actions import CARE_ACTIONS
from src.agent import build_plant_context, due_tasks
from src.digest import format_digest, build_keyboard
from src.intervals import explain_interval
from src.weather import get_forecast, derive_climate

# Derived from data/fertilizer.md. The sheet is authoritative once populated;
# this is the seed, used for the paste-ready table and for previewing before
# the columns exist.
PLANNED = {
    "Monstera":        ("ALLPURPOSE", "manual"),
    "Fiddle Leaf Fig": ("ALLPURPOSE", "manual"),
    "Yucca":           ("SUCCULENT", "manual"),
    "Peace Lily":      ("ALLPURPOSE", "manual"),
    "Snake Plant":     ("SUCCULENT", "manual"),
    "Bougainvillea":   ("BLOOM", "manual"),
    "Snail Vine":      ("BLOOM", "manual"),
    "Geranium":        ("BLOOM", "manual"),
    "Blackberry":      ("GRANULAR", "manual"),
    "Crown of Thorns": ("SUCCULENT", "manual"),
    "Azalea":          ("ACID", "sprinkler"),
    "Camellia":        ("ACID", "sprinkler"),
    "Spider Plant":    ("ALLPURPOSE_HALF", "sprinkler"),
    "Black Pagoda":    ("ALLPURPOSE", "manual"),
    # Mature fruit trees -- new rows, all on the irrigation system.
    "Avocado":         ("CITRUS", "sprinkler"),
    "Loquat":          ("CITRUS", "sprinkler"),
    "Pomegranate":     ("CITRUS", "sprinkler"),
    "Fig":             ("CITRUS", "sprinkler"),
    "Orange":          ("CITRUS", "sprinkler"),
}

NEW_ROWS = ["Avocado", "Loquat", "Pomegranate", "Fig", "Orange"]
TREE_DEFAULTS = ("outdoor", "direct", "low", "mature tree, in ground")


def print_table():
    existing = [n for n in PLANNED if n not in NEW_ROWS]

    print("\n=== Fill these two columns on the existing rows ===\n")
    print(f"{'Name':<18} {'Fertilizer':<18} Watering")
    print("-" * 48)
    for name in existing:
        fert, watering = PLANNED[name]
        print(f"{name:<18} {fert:<18} {watering}")

    env, light, humidity, notes = TREE_DEFAULTS
    print("\n=== Add these five rows ===\n")
    cols = ["Name", "Environment", "Light", "Humidity", "Notes",
            "Last Watered", "Last Fertilized", "Status", "Fertilizer", "Watering"]
    print("\t".join(cols))
    for name in NEW_ROWS:
        fert, watering = PLANNED[name]
        print("\t".join([name, env, light, humidity, notes, "", "", "OK", fert, watering]))

    print("\n=== Then set Status = OK on every row ===")
    print("(clears the saturated PENDING_ values from previous digests)\n")


def _rows(live):
    from src.storage import PlantDB
    db = PlantDB()
    _rows.history = db.get_history_summary()
    df = db.get_inventory()
    rows = df.to_dict("records")

    if live:
        return rows

    # Overlay the planned values so the digest can be previewed before the
    # columns exist, and add the tree rows that aren't in the sheet yet.
    by_name = {r.get("Name"): r for r in rows}
    for name, (fert, watering) in PLANNED.items():
        row = by_name.get(name)
        if row is None:
            env, light, humidity, notes = TREE_DEFAULTS
            row = {"Name": name, "Environment": env, "Light": light,
                   "Humidity": humidity, "Notes": notes,
                   "Last Watered": "", "Last Fertilized": "", "Status": "OK"}
            rows.append(row)
        row["Fertilizer"] = fert
        row["Watering"] = watering
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="store_true",
                        help="print the paste-ready sheet values and exit")
    parser.add_argument("--live", action="store_true",
                        help="use the sheet exactly as it is, with no planned overlay")
    args = parser.parse_args()

    if args.table:
        print_table()
        return

    climate = derive_climate(get_forecast())
    print("\n=== Climate ===")
    for k, v in climate.items():
        print(f"  {k:<18} {round(v, 2) if isinstance(v, float) else v}")

    rows = _rows(args.live)
    source = "live sheet" if args.live else "live sheet + planned overlay"
    print(f"\n=== Intervals ({len(rows)} plants, {source}) ===\n")

    tasks = []
    lines = []
    for row in rows:
        # Same path the real run takes -- no parallel reimplementation to drift.
        plant = build_plant_context(row, getattr(_rows, "history", None), climate)

        cells = []
        for action in CARE_ACTIONS:
            result = explain_interval(
                action, plant, plant["_care"], climate,
                days_since=plant["_days_since"].get(action))
            if result is None:
                continue
            if result["suppressed_reason"]:
                cells.append(f"{action}=✗")
            elif action not in plant["_intervals"]:
                cells.append(f"{action}=✗")          # dropped by a cross-action rule
            else:
                days = plant["_days_since"].get(action)
                due = days is None or days >= result["days"]
                cells.append(f"{action}={result['days']}d{'*' if due else ''}")

        lines.append(f"  {plant['name']:<18} {'  '.join(cells)}")
        tasks.extend(due_tasks(plant))

    print("\n".join(lines))
    print("\n  ✗ = does not apply    * = due now\n")
    print("=== Digest (everything due; the real run lets Gemini prune this) ===\n")
    print(format_digest(tasks, "Dry run — no message was sent."))

    rows_out = build_keyboard(tasks)["inline_keyboard"]
    print(f"\n=== Keyboard ({len(rows_out)} rows) ===\n")
    for row in rows_out:
        print(f"  [{row[0]['text']}]  →  {row[0]['callback_data']}")


if __name__ == "__main__":
    main()
