"""Subprocess output must remain readable when progress consumers fail."""

import io
from unittest.mock import Mock

import pytest

from adapters.g3mtool_adapter import G3MToolManager
from services.g3mtool_patching_service import MOD_TYPE_G3MPATCH, G3MToolPatchingService


@pytest.mark.parametrize("fail_callback", [False, True])
def test_output_collection_preserves_text_and_drains_after_callback_error(
    fail_callback,
):
    manager = object.__new__(G3MToolManager)
    text = (
        "Applying patch: 10%\rApplying patch: 50%\n"
        + "output\n" * 10_000
        + "Applying patch: 100%"
    )
    stream = io.StringIO(text)
    chunks = []
    callback = Mock(side_effect=RuntimeError("closed view") if fail_callback else None)

    manager._stream_output(stream, chunks, callback)

    assert "".join(chunks) == text
    assert stream.read() == ""
    assert len(chunks) < 11_000
    assert callback.call_count == (1 if fail_callback else 3)


@pytest.mark.parametrize("cancel_in_handler", [False, True])
def test_cancelled_patching_never_accepts_warning(cancel_in_handler):
    patcher = G3MToolPatchingService(Mock(local_config={}), Mock())

    def cancel(*_args):
        patcher.cancel()
        return True

    patcher.warning_handler = Mock(side_effect=cancel)
    if not cancel_in_handler:
        patcher.cancel()

    assert not patcher._request_warning("Patch failed")
    assert patcher.warning_handler.call_count == int(cancel_in_handler)


def test_cancellation_during_final_data_step_is_not_success(tmp_path):
    patcher = G3MToolPatchingService(Mock(local_config={}), Mock())
    output = tmp_path / "output.win"

    def apply(*_args):
        output.write_bytes(b"result")
        patcher.cancel()
        return True

    patcher._apply_single_mod = Mock(side_effect=apply)

    assert not patcher._apply_data_steps(
        "original.win",
        [[("patch.g3mpatch", MOD_TYPE_G3MPATCH, None)]],
        str(output),
        None,
        "1",
        0,
        100,
        "Chapter 1",
    )


def test_execute_separates_child_arguments_from_host_options(monkeypatch):
    manager = G3MToolManager(Mock(local_config={"custom_xdelta_path": "delta.exe"}))
    monkeypatch.setattr(manager, "refresh_executable", lambda: "G3MTool.exe")
    manager._run = Mock(return_value=(0, "", ""))

    manager.execute("script.csx", ["--output", "payload"], output_path="actual.win")

    assert manager._run.call_args.args[0] == [
        "G3MTool.exe",
        "execute",
        "script.csx",
        "--output",
        "actual.win",
        "--xdelta-path",
        "delta.exe",
        "--",
        "--output",
        "payload",
    ]
