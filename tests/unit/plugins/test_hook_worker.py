"""Unit tests for test hook worker."""

from unittest.mock import Mock

from workers.plugin_hook_worker import PluginHookThread


def test_plugin_hook_worker_maps_progress_and_executes_hook():
    runtime_service = Mock()

    def _run_hook(hook_name, task_runtime, *_args):
        assert hook_name == "after_mod_apply_before_launch"
        task_runtime.set_progress(50, "half")
        return [True]

    runtime_service.execute_hook_with_runtime.side_effect = _run_hook
    thread = PluginHookThread(
        runtime_service,
        "after_mod_apply_before_launch",
        ({"deltarune_1": []}, False),
        base_progress=96,
        progress_span=4,
    )
    progress = []
    status = []
    finished = []
    thread.progress_update.connect(lambda value, message: progress.append((value, message)))
    thread.status_update.connect(lambda message, level: status.append((message, level)))
    thread.finished.connect(lambda ok: finished.append(ok))

    thread.run()

    assert (98, "half") in progress
    assert finished == [True]
    assert status == []


def test_plugin_hook_worker_calls_cancel_hook_when_cancelled():
    runtime_service = Mock()

    def _run_hook(hook_name, task_runtime, *_args):
        if hook_name == "mod_apply_cancelled":
            return [True]
        thread.cancel()
        task_runtime.raise_if_cancelled()
        return [True]

    runtime_service.execute_hook_with_runtime.side_effect = _run_hook
    thread = PluginHookThread(
        runtime_service,
        "after_mod_apply_before_launch",
        ({}, False),
        base_progress=0,
        progress_span=100,
    )
    finished = []
    thread.finished.connect(lambda ok: finished.append(ok))

    thread.run()

    assert finished == [False]
    assert runtime_service.execute_hook_with_runtime.call_args_list[-1].args[0] == "mod_apply_cancelled"
