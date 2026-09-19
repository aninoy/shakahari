"""Fertilizer product registry and sheet-value normalization."""
import pytest

from src.fertilizers import FERTILIZERS, normalize, product_of, interval_of, strength_of


def test_every_code_has_the_fields_the_digest_and_engine_need():
    for code, entry in FERTILIZERS.items():
        assert entry["product"], f"{code} has no product name"
        assert entry["icon"], f"{code} has no icon"
        assert isinstance(entry["interval"], int) and entry["interval"] > 0
        assert "strength" in entry, f"{code} missing strength key"


def test_the_three_all_purpose_codes_share_one_product_but_differ_in_cadence():
    """Same bottle, different dilution -- the digest groups by product so one
    trip to the shelf covers all three, but each keeps its own interval."""
    codes = ["ALLPURPOSE", "ALLPURPOSE_HALF", "SUCCULENT"]
    products = {FERTILIZERS[c]["product"] for c in codes}
    assert len(products) == 1

    intervals = [FERTILIZERS[c]["interval"] for c in codes]
    assert intervals == sorted(intervals), "expected increasing cadence"
    assert len(set(intervals)) == 3, "each dilution needs its own interval"


def test_full_strength_has_no_annotation_but_diluted_ones_do():
    assert strength_of("ALLPURPOSE") is None
    assert strength_of("ALLPURPOSE_HALF") == "½ strength"
    assert strength_of("SUCCULENT") == "½, sparing"


@pytest.mark.parametrize("raw,expected", [
    ("CITRUS", "CITRUS"),
    ("citrus", "CITRUS"),
    ("  Citrus  ", "CITRUS"),
    ("citrus-tone", "CITRUS"),
    ("Citrus Tone", "CITRUS"),
    ("citrus_tone", "CITRUS"),
    ("ALLPURPOSE_HALF", "ALLPURPOSE_HALF"),
    ("allpurpose half", "ALLPURPOSE_HALF"),
    ("all-purpose-half", "ALLPURPOSE_HALF"),
    ("bloom", "BLOOM"),
    ("Bloom Booster", "BLOOM"),
    ("acid", "ACID"),
    ("granular", "GRANULAR"),
    ("succulent", "SUCCULENT"),
])
def test_normalize_accepts_the_shapes_a_human_would_actually_type(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, "compost", "Miracle Gro???", "12-12-12"])
def test_normalize_refuses_to_guess_on_blank_or_unknown_values(raw):
    """A wrong fertilizer is worse than an unassigned one -- unknown must land
    in the visible 'Not set' group, never a silent default."""
    assert normalize(raw) is None


def test_lookup_helpers_tolerate_an_unmapped_plant():
    assert product_of(None) is None
    assert interval_of(None) is None
    assert strength_of(None) is None


def test_interval_of_reflects_the_doc_cadences():
    """data/fertilizer.md: succulents 2-3x/year, Spider Plant every 6-8 weeks,
    bloom booster every 7-14 days."""
    assert interval_of("SUCCULENT") >= 100
    assert 40 <= interval_of("ALLPURPOSE_HALF") <= 60
    assert interval_of("BLOOM") <= 14
    assert interval_of("ALLPURPOSE") == 14
