"""Fertilizer product registry.

The `Fertilizer` column in the Plants sheet holds a short code; this module
holds what that code means. Keeping product behaviour here (rather than in the
spreadsheet) means the sheet stays editable without turning into config.

ALLPURPOSE / ALLPURPOSE_HALF / SUCCULENT are deliberately the same `product`:
they are one bottle at three dilutions. The digest groups by product -- one trip
to one shelf -- while each code keeps its own interval and strength annotation.

Cadences come from data/fertilizer.md.
"""

FERTILIZERS = {
    "CITRUS": {
        "product": "Espoma Citrus-tone",
        "strength": None,
        "interval": 120,
        "icon": "🍊",
    },
    "ACID": {
        "product": "Vigoro Azalea/Camellia 10-8-8",
        "strength": None,
        "interval": 35,
        "icon": "🌺",
    },
    "BLOOM": {
        "product": "Miracle-Gro Bloom Booster",
        "strength": None,
        "interval": 10,
        "icon": "🌸",
    },
    "GRANULAR": {
        "product": "All-Purpose 16-16-16",
        "strength": None,
        "interval": 60,
        "icon": "🌾",
    },
    "ALLPURPOSE": {
        "product": "Miracle-Gro All-Purpose",
        "strength": None,
        "interval": 14,
        "icon": "🧪",
    },
    "ALLPURPOSE_HALF": {
        "product": "Miracle-Gro All-Purpose",
        "strength": "½ strength",
        "interval": 49,
        "icon": "🧪",
    },
    "SUCCULENT": {
        "product": "Miracle-Gro All-Purpose",
        "strength": "½, sparing",
        "interval": 120,
        "icon": "🧪",
    },
}

# Spellings a human might reasonably type into the sheet, keyed by their
# canonical form (uppercased, separators collapsed to '_').
ALIASES = {
    "CITRUS_TONE": "CITRUS",
    "ESPOMA_CITRUS_TONE": "CITRUS",
    "ACID_LOVING": "ACID",
    "AZALEA": "ACID",
    "CAMELLIA": "ACID",
    "BLOOM_BOOSTER": "BLOOM",
    "ALL_PURPOSE": "ALLPURPOSE",
    "ALL_PURPOSE_HALF": "ALLPURPOSE_HALF",
    "ALLPURPOSE_HALF_STRENGTH": "ALLPURPOSE_HALF",
    "HALF": "ALLPURPOSE_HALF",
    "16_16_16": "GRANULAR",
}


def _canonical(value):
    """Uppercase and collapse spaces/hyphens/underscores into single '_'."""
    out = []
    prev_sep = False
    for ch in str(value).strip().upper():
        if ch in " -_":
            if out and not prev_sep:
                out.append("_")
                prev_sep = True
        else:
            out.append(ch)
            prev_sep = False
    return "".join(out).rstrip("_")


def normalize(value):
    """Map a raw sheet cell to a registry code, or None if unrecognized.

    Returning None is load-bearing: an unknown value must surface in the
    digest's '❓ Not set' group rather than silently defaulting to a product.
    Feeding a plant the wrong fertilizer is worse than not feeding it."""
    if value is None:
        return None

    key = _canonical(value)
    if not key:
        return None
    if key in FERTILIZERS:
        return key
    if key in ALIASES:
        return ALIASES[key]

    # "ALLPURPOSEHALF" -- separators omitted entirely.
    squashed = key.replace("_", "")
    for code in FERTILIZERS:
        if squashed == code.replace("_", ""):
            return code
    for alias, code in ALIASES.items():
        if squashed == alias.replace("_", ""):
            return code

    return None


def _field(code, name):
    if code is None:
        return None
    return FERTILIZERS.get(code, {}).get(name)


def product_of(code):
    """Display name of the bottle -- what the digest groups by."""
    return _field(code, "product")


def interval_of(code):
    """Base days between feedings for this product and dilution."""
    return _field(code, "interval")


def strength_of(code):
    """Dilution annotation for a plant's digest line, or None at full strength."""
    return _field(code, "strength")


def icon_of(code):
    return _field(code, "icon")
