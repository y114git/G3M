from unittest.mock import Mock


def test_worker_emits_service_result(monkeypatch):
    from services.user_data_root_service import DataRootChangeResult
    from workers.user_data_root_worker import UserDataRootWorker

    prepare = Mock(return_value=DataRootChangeResult("ready", "C:/selected"))
    monkeypatch.setattr("workers.user_data_root_worker.prepare_data_root_change", prepare)
    worker = UserDataRootWorker("C:/current", "C:/selected", copy_data=True)
    completed = Mock()
    worker.completed.connect(completed)

    worker.run()

    completed.assert_called_once_with(DataRootChangeResult("ready", "C:/selected"))
    prepare.assert_called_once()
    assert prepare.call_args.args == ("C:/current", "C:/selected")
    assert prepare.call_args.kwargs["copy_data"] is True
    assert callable(prepare.call_args.kwargs["cancelled"])
