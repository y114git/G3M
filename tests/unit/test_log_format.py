import logging
import sys

import pytest

from utils.log_format import ConciseFormatter


def _render(error: BaseException, level=logging.WARNING, message="Could not save") -> str:
    try:
        raise error
    except BaseException:
        record = logging.LogRecord("g3m", level, __file__, 1, message, None, sys.exc_info())
    return ConciseFormatter("%(levelname)s %(message)s").format(record)


def test_an_expected_failure_is_one_line_without_a_traceback():
    text = _render(PermissionError(5, "Access is denied"))

    assert "Traceback" not in text
    assert text.splitlines() == ["WARNING Could not save: PermissionError: [Errno 5] Access is denied"]


def test_a_message_that_already_names_the_error_is_not_repeated():
    text = _render(OSError("disk full"), message="Could not save: disk full")

    assert text == "WARNING Could not save: disk full"


@pytest.mark.parametrize("error", [AttributeError("x"), KeyError("k"), TypeError("t")])
def test_a_probable_bug_keeps_its_traceback(error):
    assert "Traceback" in _render(error)


def test_a_critical_record_keeps_its_traceback_for_any_error():
    assert "Traceback" in _render(OSError("boom"), level=logging.CRITICAL)


def test_the_environment_switch_restores_full_tracebacks(monkeypatch):
    monkeypatch.setenv("G3M_LOG_TRACEBACKS", "1")

    assert "Traceback" in _render(OSError("boom"))
