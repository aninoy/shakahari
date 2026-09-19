from src.callbacks import (
    encode_fert_done,
    encode_task_button,
    encode_alldone,
    encode_action_done,
    encode_log_select,
    encode_log_action,
    encode_log_back,
    decode_callback,
)


def test_encode_task_button():
    assert encode_task_button("WATER", "Monstera") == "t:WATER:Monstera"


def test_encode_alldone():
    assert encode_alldone("2026-08-19") == "alldone:2026-08-19"


def test_encode_action_done():
    assert encode_action_done("WATER", "2026-08-19") == "donetype:WATER:2026-08-19"


def test_encode_log_select():
    assert encode_log_select("Peace Lily") == "logsel:Peace Lily"


def test_encode_log_action():
    assert encode_log_action("Peace Lily", "FERTILIZE") == "logact:Peace Lily:FERTILIZE"


def test_encode_log_back():
    assert encode_log_back() == "logback"


def test_decode_task_button():
    assert decode_callback("t:WATER:Monstera") == {"kind": "task", "action": "WATER", "plant": "Monstera"}


def test_decode_alldone():
    assert decode_callback("alldone:2026-08-19") == {"kind": "alldone", "date": "2026-08-19"}


def test_decode_action_done():
    assert decode_callback("donetype:WATER:2026-08-19") == {
        "kind": "donetype", "action": "WATER", "date": "2026-08-19",
    }


def test_decode_log_select():
    assert decode_callback("logsel:Fiddle Leaf Fig") == {"kind": "logsel", "plant": "Fiddle Leaf Fig"}


def test_decode_log_action():
    assert decode_callback("logact:Fiddle Leaf Fig:MIST") == {
        "kind": "logact", "plant": "Fiddle Leaf Fig", "action": "MIST",
    }


def test_decode_log_back():
    assert decode_callback("logback") == {"kind": "logback"}


def test_decode_unknown_falls_back_gracefully():
    assert decode_callback("garbage:data:here:too:many:parts") == {"kind": "unknown"}
    assert decode_callback("") == {"kind": "unknown"}


def test_decode_noop_button():
    """Spent digest buttons (already-tapped rows) carry callback_data "noop" and
    must decode to their own kind, distinct from "unknown", so the handler can
    acknowledge them silently instead of showing an error."""
    assert decode_callback("noop") == {"kind": "noop"}


# --- fertilizer-product bulk buttons ---------------------------------------

def test_encode_fert_done_names_the_product_and_the_date():
    assert encode_fert_done("CITRUS", "2026-09-19") == "donefert:CITRUS:2026-09-19"


def test_decode_recognizes_a_fertilizer_bulk_tap():
    assert decode_callback("donefert:BLOOM:2026-09-19") == {
        "kind": "donefert", "code": "BLOOM", "date": "2026-09-19",
    }


def test_the_longest_realistic_fert_payload_fits_telegrams_64_byte_limit():
    payload = encode_fert_done("ALLPURPOSE_HALF", "2026-12-31")
    assert len(payload.encode("utf-8")) <= 64


def test_donefert_is_a_distinct_kind_from_donetype():
    """Overloading donetype would make FERTILIZE collide with itself in the
    recorder's prefix matching."""
    assert decode_callback("donetype:FERTILIZE:2026-09-19")["kind"] == "donetype"
    assert decode_callback("donefert:CITRUS:2026-09-19")["kind"] == "donefert"


def test_a_malformed_fert_payload_is_unknown_not_a_partial_match():
    assert decode_callback("donefert:CITRUS")["kind"] == "unknown"
    assert decode_callback("donefert")["kind"] == "unknown"
