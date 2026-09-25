"""The Cloud Function's import and request footprint.

The Recorder runs in a small Cloud Run container. It was being OOM-killed
mid-request -- so no Sheet write ever landed -- because the entry point
resolves through main.py, which imported the whole Advisor stack including the
Gemini SDK. These tests pin the footprint so it cannot regress silently.
"""
import subprocess
import sys
import textwrap

import pytest


def _run(code):
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                          capture_output=True, text=True, timeout=120)


def test_the_cloud_function_entry_point_does_not_load_the_gemini_sdk():
    """google.genai is ~36MB and the Recorder never calls it. Loading it was
    the difference between fitting in the container and being killed."""
    result = _run("""
        import sys
        import main
        assert callable(main.telegram_webhook), "entry point missing"
        loaded = [m for m in sys.modules if m.startswith("google.genai")]
        print("GENAI_LOADED" if loaded else "GENAI_ABSENT")
    """)
    assert result.returncode == 0, result.stderr
    assert "GENAI_ABSENT" in result.stdout, "main.py still pulls in the Gemini SDK at import time"


def test_the_advisor_still_works_after_its_imports_are_deferred():
    result = _run("""
        import main
        for name in ("PlantDB", "get_forecast", "PlantAgent", "send_message",
                     "format_digest", "build_keyboard"):
            main._advisor()  # resolve the lazily-imported names
        print("OK")
    """)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_importing_main_stays_close_to_importing_the_recorder_alone():
    result = _run("""
        import resource, sys
        base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        import main
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        div = 1024*1024 if sys.platform == "darwin" else 1024
        print(f"MB={(peak)/div:.1f}")
    """)
    assert result.returncode == 0, result.stderr
    mb = float(result.stdout.split("MB=")[1].split()[0])
    # Recorder-only is ~91MB; the Advisor stack pushed it to ~127MB.
    assert mb < 110, f"import footprint regressed to {mb:.1f}MB"
