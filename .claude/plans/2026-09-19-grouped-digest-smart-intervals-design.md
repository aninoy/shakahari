# Grouped Digest + Context-Aware Intervals — Design

## Problem

Three problems, one root cause.

**1. The digest is organized by plant, but care happens by action.** Today
`format_tasks()` emits one flat line per task in whatever order Gemini returned
them:

```
🔴💧 Monstera — 12d overdue · 🔁10d
🟡🧪 Azalea — 30d overdue · 🔁14d
🟢🔄 Pothos — 2d overdue · 🔁7d
🟡💧 Peace Lily — 4d overdue · 🔁14d
```

Watering is interleaved with fertilizing and rotating, so completing "all the
watering" means scanning the whole list and mentally regrouping it. Worse for
fertilizing: four different products are in play, and the single
`Mark fertilizing complete` bulk button spans all of them — tapping it claims
you fed the Azalea its acid formula and the Bougainvillea its bloom booster in
the same tap.

**2. Every interval is a hardcoded constant.** `MIN_ACTION_INTERVALS`
(`src/agent.py:10-19`) is a flat dict — `FERTILIZE: 14` for every plant in every
season, `MIST: 2` regardless of humidity. This contradicts knowledge the project
already holds:

- `data/fertilizer.md` says Snake Plant / Yucca / Crown of Thorns want feeding
  **2–3× a year**, and Spider Plant every **6–8 weeks**. The bot nags all four
  every 14 days.
- The same doc says to stop feeding entirely **Nov–Feb**. The bot has no notion
  of season.
- `MIST: 2` fires year-round, but LA humidity is currently 67–80% — misting is
  pointless. In a 20% Santa Ana it genuinely matters.
- Weather is fetched and passed to Gemini as prose, but the post-filter with the
  final say ignores it entirely. **Model and safety-net disagree**, so Gemini's
  weather reasoning is silently overridden by a constant.

**3. The sheet knows things the code can't read.** Azalea, Camellia, and Spider
Plant each carry `Notes = "in ground, watered by sprinkler"`. Nothing parses
that, so all three get watering reminders that can never be acted on. The five
mature fruit trees in `data/fertilizer.md` aren't in the sheet at all.

The visible symptom of all three: **every one of the 14 plants currently has a
saturated `Status`** — e.g. Monstera is
`PENDING_ROTATE_MIST_CHECK_WATER_FERTILIZE_MOVE_PRUNE_REPOT`. Every action is
pending for every plant, because recommendations fire on constants and are too
noisy to act on, so nothing ever gets marked done.

## Goals

- Group digest tasks by action, so one action can be completed across all its
  plants in a single pass.
- Sub-divide fertilizing by product, so a bulk "done" tap means one real-world
  act with one bottle.
- Replace flat constants with per-plant intervals computed from real signals —
  evapotranspiration, rain (past *and* forecast), humidity, season, environment,
  irrigation method, and fertilizer type.
- Stop recommending watering for plants on an irrigation system.
- Make the engine deterministic and testable, and feed the *same* numbers to
  Gemini that the post-filter enforces — one source of truth.
- Show the reasoning in the digest, compactly (`🔁10d→8d (high ET₀)`).

## Non-goals

- No change to the Advisor/Recorder split, the daily cadence, or the webhook
  security model.
- No new external API. Open-Meteo already serves every signal needed.
- No change to `CareHistory` schema, `/log` flow, or plant matching semantics.
- Not modelling soil sensors, pot volume, or per-plant calibration.

## Decisions taken

| Decision | Choice |
|---|---|
| Fertilizer assignment | New `Fertilizer` column in the `Plants` sheet |
| Irrigation | New `Watering` column: `manual` / `sprinkler` / `drip` / `established` |
| Fruit trees | Added as 5 new rows, all `sprinkler` + `CITRUS` |
| Sheet edits | Paste-ready rows printed; nothing in this change writes to the live sheet |
| Status saturation | Reset to `OK` as part of this work |
| Buttons | Regrouped; per-plant kept, bulk per action, bulk per fertilizer product |
| Unmapped plants | `❓ Not set` group — visible, never silently defaulted |
| Group ordering | By urgency (most overdue first) |
| Interval engine | Deterministic `src/intervals.py`; Gemini reasons over its output |
| Phasing | One combined change |

---

## Architecture

```
Open-Meteo (extended vars)          Plants sheet
  et0, rain past+forecast,            Name, Environment, Light, Humidity,
  humidity, daylight                  Fertilizer, Watering, Last *
        │                                   │
        └──────────────┬────────────────────┘
                       ▼
             src/intervals.py  ◄── src/fertilizers.py (product registry)
             pure, no I/O          src/plant_api.py   (watering guidelines)
                       │
        per-plant, per-action effective interval
        + the adjustments that produced it
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
  Gemini prompt                 post-filter
  (reasons over them)           (enforces them)   ← same numbers, no disagreement
                       │
                       ▼
               src/digest.py
        group by action → sub-group by product → sort by urgency
                       │
                       ▼
              message + keyboard
```

The key structural fix is the join at the bottom: today the prompt gets prose
weather and the filter gets constants. After this, both consume one computed
value per (plant, action).

---

## Component 1 — `src/fertilizers.py` (new)

The sheet column holds a *token*; the registry holds what that token means. This
keeps the sheet editable without putting product behavior in a spreadsheet.

```python
FERTILIZERS = {
    "CITRUS":     {"product": "Espoma Citrus-tone",            "strength": None,
                   "interval": 120, "icon": "🍊"},
    "ACID":       {"product": "Vigoro Azalea/Camellia 10-8-8", "strength": None,
                   "interval": 35,  "icon": "🌺"},
    "BLOOM":      {"product": "Miracle-Gro Bloom Booster",     "strength": None,
                   "interval": 10,  "icon": "🌸"},
    "GRANULAR":   {"product": "All-Purpose 16-16-16",          "strength": None,
                   "interval": 60,  "icon": "🌾"},
    "ALLPURPOSE": {"product": "Miracle-Gro All-Purpose",       "strength": None,
                   "interval": 14,  "icon": "🧪"},
    "ALLPURPOSE_HALF": {"product": "Miracle-Gro All-Purpose",  "strength": "½ strength",
                   "interval": 49,  "icon": "🧪"},
    "SUCCULENT":  {"product": "Miracle-Gro All-Purpose",       "strength": "½, sparing",
                   "interval": 120, "icon": "🧪"},
}
```

**Why `product` is separate from the code:** the last three codes are the same
bottle at different dilutions and cadences. The digest groups by `product`, so
all three collapse under one `🧪 Miracle-Gro All-Purpose` heading — one trip to
one shelf — while each plant's line carries its own `strength` annotation and its
own interval. Grouping by bottle serves "do it all in one go"; strength and
interval are execution detail that belong on the plant's line.

`normalize(value) -> code | None` maps a sheet cell to a code: uppercase, strip,
collapse whitespace/hyphens, then match codes and a small alias table
(`"citrus-tone"`, `"citrus tone"` → `CITRUS`). Unrecognized or blank → `None`,
rendering as the `❓ Not set` group. **Never guess a default** — a wrong
fertilizer is worse than an unassigned one.

---

## Component 2 — sheet changes

Two new columns on `ShakahariDB → Plants` (any position; `save()` does a
full-sheet rewrite from `df.columns`, so new columns round-trip safely).

`Watering` vocabulary:

| Value | Engine behavior |
|---|---|
| `manual` | Full engine — ET₀, rain, humidity, season all apply |
| `sprinkler` / `drip` | **WATER and MIST suppressed entirely**; plant still surfaces for FERTILIZE, PRUNE, REPOT, CHECK, MOVE |
| `established` | Long base interval, ET₀ response damped ~70% — deep roots buffer short-term weather in a way pots don't |

Blank `Watering` defaults to `manual` (the safe reading: assume you water it).
This is the one place a default is inferred, and it errs toward reminding you.

### Paste-ready rows

**Existing 14 — fill in the two new columns:**

| Name | Fertilizer | Watering |
|---|---|---|
| Monstera | ALLPURPOSE | manual |
| Fiddle Leaf Fig | ALLPURPOSE | manual |
| Yucca | SUCCULENT | manual |
| Peace Lily | ALLPURPOSE | manual |
| Snake Plant | SUCCULENT | manual |
| Bougainvillea | BLOOM | manual |
| Snail Vine | BLOOM | manual |
| Geranium | BLOOM | manual |
| Blackberry | GRANULAR | manual |
| Crown of Thorns | SUCCULENT | manual |
| Azalea | ACID | sprinkler |
| Camellia | ACID | sprinkler |
| Spider Plant | ALLPURPOSE_HALF | sprinkler |
| Black Pagoda | ALLPURPOSE | manual |

**Five new rows — the fruit trees:**

| Name | Environment | Light | Humidity | Notes | Last Watered | Last Fertilized | Status | Fertilizer | Watering |
|---|---|---|---|---|---|---|---|---|---|
| Avocado | outdoor | direct | low | mature tree, in ground | | | OK | CITRUS | sprinkler |
| Loquat | outdoor | direct | low | mature tree, in ground | | | OK | CITRUS | sprinkler |
| Pomegranate | outdoor | direct | low | mature tree, in ground | | | OK | CITRUS | sprinkler |
| Fig | outdoor | direct | low | mature tree, in ground | | | OK | CITRUS | sprinkler |
| Orange | outdoor | direct | low | mature tree, in ground | | | OK | CITRUS | sprinkler |

Inventory goes 14 → 19, matching `data/fertilizer.md`. `Last Watered` /
`Last Fertilized` left blank — unknown, and the engine reads blank as "never",
which is correct.

**Status reset:** set `Status = OK` for all 19 rows. Otherwise the first digest
is computed against a backlog claiming everything is pending everything, and new
recommendations are indistinguishable from stale ones.

---

## Component 3 — `src/intervals.py` (new)

Pure functions, no I/O, fully unit-testable. One entry point:

```python
def effective_interval(action, plant, care, climate, today) -> Interval | None
# Interval = {"days": int, "base": int, "adjustments": [(label, delta)],
#             "suppressed_reason": str | None}
# Returns None when the action does not apply at all.
```

`climate` is a small struct derived once per run: `et0_mean_3d`, `rain_past_3d`,
`rain_next_2d`, `humidity_mean`, `temp_max_next_2d`, `daylight_hours`, and
`season` (`GROWING` / `SHOULDER` / `DORMANT`).

**Season** comes from `daylight_duration`, not hardcoded months — location-correct
and needs no calendar table. LA thresholds: `>11.5h` GROWING, `10.5–11.5h`
SHOULDER, `<10.5h` DORMANT (≈ Nov–Feb, matching the doc).

**WATER** — suppressed outright for `sprinkler` / `drip`. Otherwise base is
`care["max_watering_days"]` from `plant_api`, then:
- *Evaporative demand*: `et0_mean_3d` vs LA's ~3.3 mm/day reference. Scale by
  `ref/et0`, clamped `[0.6, 1.5]`. Today's 4.0 mm/day → ×0.83, turning a 10d
  interval into 8d; January (~1.5) stretches it toward 15d. Damped ~70% for
  `established`.
- *Rain*, outdoor only: `rain_past_3d ≥ 10mm` adds days proportionally;
  `rain_next_2d ≥ 5mm` defers. Indoor ignores rain entirely — the current prompt
  asks Gemini to do this in prose and has no way to enforce it.
- *Humidity*: `< 35%` shortens modestly. *Season*: DORMANT ×1.4.

**FERTILIZE** — base is the fertilizer type's `interval`.
- DORMANT → suppressed (`"dormant season"`). The doc's "stop entirely Nov–Feb",
  enforced rather than hoped for. SHOULDER → ×1.5.
- `rain_next_2d ≥ 10mm` and outdoor → defer (runoff before uptake).

**MIST** — suppressed for `sprinkler` / `drip`. Otherwise base 2d, humidity-
dominated: `RH ≥ 60%` → ×4 (today's 67–80% makes misting near-pointless);
`RH < 40%` → ×1.

**ROTATE** 7d, ×1.5 DORMANT, suppressed for in-ground plants (you can't rotate a
tree). **PRUNE / REPOT** growing-season gated; REPOT suppressed for in-ground.
**MOVE** becomes signal-driven: `temp_max_next_2d > 35°C` on an outdoor potted
plant is a real "move it to shade" trigger rather than an arbitrary 14-day timer;
suppressed for in-ground. **CHECK** 3d, stretched in DORMANT.

**Safety clamps.** Every result is clamped to a per-action `[floor, ceiling]` so
no combination of modifiers produces an absurd value (WATER never below 2d). The
clamps are the surviving descendant of `MIN_ACTION_INTERVALS`; the flat dict is
deleted.

---

## Component 4 — `src/digest.py` (new)

Grouping and formatting move out of `main.py`, which already carries
orchestration plus two formatters. `main.py` keeps `main()` only.

```
🌿 Plant Care Tasks (2026-09-19)
Warm and dry — watering is running ahead of schedule.

💧 WATER · 3 plants
🔴 Monstera — 12d · 🔁10d→8d (high ET₀)
🟡 Peace Lily — 15d · 🔁14d
🟢 Black Pagoda — 11d · 🔁10d→8d (high ET₀)

🧪 FERTILIZE · 5 plants
  🍊 Espoma Citrus-tone
  🔴 Avocado — never · 🔁120d
  🟡 Orange — never · 🔁120d
  🌸 Miracle-Gro Bloom Booster
  🔴 Bougainvillea — 24d · 🔁10d
  🟡 Geranium — 12d · 🔁10d
  ❓ Not set
  🟢 Mint — never · 🔁14d

🔄 ROTATE · 1 plant
🟢 Fiddle Leaf Fig — 9d · 🔁7d
```

**Ordering.** Groups sort by max overdue ratio (`days_since / threshold`) across
members, descending; ties fall back to `CARE_ACTIONS` order. `never` sorts as
maximally overdue. Sub-groups and plant lines sort the same way. `❓ Not set`
always sorts last within FERTILIZE regardless of urgency, so a misconfiguration
never buries real work.

**Keyboard.**

```
[💧 Water Monstera]                    t:WATER:Monstera
[💧 Water Peace Lily]                  t:WATER:Peace Lily
...
[💧 Mark watering complete]            donetype:WATER:2026-09-19
[🍊 Mark Citrus-tone feeding done]     donefert:CITRUS:2026-09-19
[🌸 Mark Bloom Booster feeding done]   donefert:BLOOM:2026-09-19
[✅ Mark everything above done]        alldone:2026-09-19
```

Per-plant buttons keep the existing `t:ACTION:Plant` encoding unchanged — the
plant's product is looked up from the sheet, so no sub-type rides in the
callback. Only the bulk button needs it. `donefert` is a **new third kind**
rather than an overload of `donetype`, because `recorder._replace_action_rows`
prefix-matches `donetype:{action}:` and overloading would make FERTILIZE collide
with itself. Three colon-separated parts keeps it inside both
`decode_callback`'s strict part-count style and Telegram's 64-byte
`callback_data` limit (longest realistic: `donefert:ALLPURPOSE_HALF:2026-09-19`
= 35 bytes).

The generic `Mark watering complete` button is kept for every action; for
FERTILIZE it is **replaced** by per-product buttons, never shown alongside them
— that ambiguous all-products tap is the bug being fixed.

---

## Component 5 — changes to existing files

**`src/weather.py`** — `get_forecast()` requests
`et0_fao_evapotranspiration`, `relative_humidity_2m_mean`, `daylight_duration`,
`temperature_2m_min`, and `forecast_days=3` (currently 1) so rain and heat
*ahead* are usable, not just behind. Return shape (the `daily` dict) unchanged.
All fields verified live against the LA coordinates. New
`derive_climate(daily) -> dict` builds the struct `intervals.py` consumes and
degrades field-by-field: a missing variable drops its modifier rather than
failing the run.

**`src/agent.py`** — delete `MIN_ACTION_INTERVALS`. Each plant in the prompt
gains an `effective_intervals` block (computed days plus adjustment labels) and
the run gains a climate summary. The prompt shifts from "apply these fixed rules"
to "here is what is due and why; use judgement about what actually needs doing
today". The post-filter then enforces the same numbers it showed the model.
Suppressed actions are omitted from the prompt entirely so they cannot be
proposed.

**`src/storage.py`** — `mark_fertilizer_done(code, date) -> list[str]` returns
the plant names marked (not a count, unlike `mark_action_done`) so the recorder
can collapse exactly those rows. Selection: `Status` contains `PENDING_FERTILIZE`
**and** `normalize(row["Fertilizer"]) == code`. Reuses existing `_clear_pending`
and `log_action`, writing `notes=f"Confirmed via {product}"` so `CareHistory`
records which product was applied. `Fertilizer` and `Watering` are read
defensively (`row.get`) so the code runs against a sheet lacking them.

**`src/callbacks.py`** — add `encode_fert_done(code, date)` and a `donefert`
branch in `decode_callback`. The existing "too many parts → unknown" test stays
valid.

**`src/recorder.py`** — a `donefert` branch mirroring `donetype`, same stale-date
refusal, plus `_replace_fert_rows(markup, plant_names, ...)` collapsing rows by
explicit name list rather than prefix scan.

---

## Testing

TDD throughout — failing test first, per repo policy.

- **`tests/test_intervals.py`** (new, the bulk of the value): table-driven cases
  pinning each modifier in isolation and combination. Dormant season suppresses
  FERTILIZE; high ET₀ shortens WATER; rain defers outdoor but not indoor
  watering; high humidity stretches MIST; `sprinkler` suppresses WATER and MIST
  but not FERTILIZE; `established` damps the ET₀ response; blank `Watering`
  defaults to `manual`; clamps hold under adversarial climate inputs; missing
  weather fields degrade to base intervals.
- **`tests/test_fertilizers.py`** (new): normalization incl. aliases, casing,
  whitespace, blank and unknown → `None`; every code has a registry entry.
- **`tests/test_digest.py`** (new): grouping, urgency ordering, `❓ Not set`
  last, product sub-grouping with strength annotations, keyboard shape incl.
  `donefert` rows and absence of a generic fertilize-all button.
- **Updated**: `tests/test_main.py` (formatter moved; message shape changed),
  `tests/test_callbacks.py` (+`donefert`), `tests/test_recorder.py`
  (+`donefert` handler). Note `FakePlantDB` there declares
  `log_task_action(self, plant_name, action, date=None)` with no `notes` kwarg —
  it needs updating or the webhook swallows a TypeError into a 200.
- **`tests/test_weather.py`** (new): `derive_climate` against a recorded
  Open-Meteo payload, including partial payloads.

**End-to-end verification** (repo policy: not "done" until seen running):
1. `python -m pytest tests/ -v` — full suite green.
2. Dry-run harness building the digest from live sheet + live weather, printing
   message and keyboard to stdout **without sending** — confirms grouping and
   intervals against real data, and that the 8 irrigated plants produce no WATER
   tasks.
3. Real send to Telegram; confirm grouping renders, then tap one per-plant
   button and one `donefert` button, verifying sheet rows and `CareHistory`
   notes.
4. Season check: re-run with a forced January daylight value; confirm FERTILIZE
   is suppressed across the board.

---

## Risks

- **Two deployment targets.** The Advisor runs on GitHub Actions cron; the
  Recorder is a separately deployed Cloud Function. A `callback_data` change
  ships in both and they can skew. Deploy the Recorder **first** — `donefert` is
  additive, so an updated Recorder handles old digests, but not the reverse.
- **Generic tree names.** `Fig` and `Orange` are ambiguous lookups for Perenual
  (`Fig` is also distinct from the cached `fiddle leaf fig`; no key collision,
  but the search may return the wrong species). Largely defused: all five trees
  are `sprinkler`, so their watering guidelines are suppressed and unused. If a
  lookup returns nonsense it affects nothing that ships.
- **Sheet edits are manual and multi-part** — two new columns, five new rows, and
  a Status reset. A partially-filled sheet still runs (blank `Fertilizer` → `❓ Not
  set`, blank `Watering` → `manual`), so it degrades visibly rather than breaking.
- **Interval tuning is a first pass.** Coefficients are reasoned from
  `data/fertilizer.md` and LA climate norms, not measured. Adjustment labels in
  the digest exist so drift is visible and correctable.
- **`relative_humidity_2m_mean`** is a relatively recent Open-Meteo daily
  aggregate. Verified live today; `derive_climate` drops the humidity modifier if
  absent rather than failing.
