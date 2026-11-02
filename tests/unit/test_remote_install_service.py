import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services import remote_install_service
from services.remote_install_service import CONFIG_KEY, RemoteInstallService

CREDENTIALS = {"member_id": "4242", "secret_key": "TopSecret"}


@pytest.fixture
def service(qapp, monkeypatch):
    monkeypatch.setattr(remote_install_service, "APP_IDS", ("G3M",))
    state = SimpleNamespace(local_config={CONFIG_KEY: CREDENTIALS})
    return RemoteInstallService(state, Mock())


def _mod(*file_ids):
    return SimpleNamespace(gamebanana_supported_files=[{"id": file_id} for file_id in file_ids])


def _reply(status=200, payload=None):
    reply = Mock(status_code=status)
    reply.json.return_value = payload if payload is not None else []
    reply.raise_for_status.side_effect = None if status < 400 else RuntimeError(f"HTTP {status}")
    return reply


def test_pair_stores_the_key_and_starts_polling(service):
    service.app_state.local_config = {}

    with patch.object(service, "poll") as poll:
        service.pair("1", "key")

    assert service.app_state.local_config[CONFIG_KEY] == {"member_id": "1", "secret_key": "key"}
    service.settings_service.write_local_config.assert_called_once()
    assert service._timer.isActive()
    poll.assert_called_once()
    service._timer.stop()


@pytest.mark.parametrize(
    "entry",
    [
        "https://gamebanana.com/mmdl/9001,Mod,111",
        "https//gamebanana.com/mmdl/9001,Mod,111",
        "gamebanana.com/mmdl/9001,mod,111",
        "http://www.gamebanana.com/mmdl/9001,MOD,111",
    ],
)
def test_entry_resolves_to_its_file(service, entry):
    emitted = []
    service.mod_ready.connect(lambda mod, file: emitted.append(file))
    mod = _mod(9000, 9001)

    with patch.object(remote_install_service.GameBananaAPI, "get_installable_mod", return_value=mod) as lookup:
        service._queue(entry)

    assert emitted == [{"id": 9001}]
    assert lookup.call_args.args == (111, "Mod")


def test_wip_entry_is_looked_up_as_a_wip(service):
    with patch.object(remote_install_service.GameBananaAPI, "get_installable_mod", return_value=_mod(5)) as lookup:
        service._queue("https://gamebanana.com/mmdl/5,Wip,7")

    assert lookup.call_args.args == (7, "Wip")


@pytest.mark.parametrize(
    "entry",
    [
        "https://evil.example.com/x.zip,Mod,1",
        "https://gamebanana.com.evil.test/mmdl/5,Mod,1",
        "https://evil.example.com/gamebanana.com/mmdl/5,Mod,1",
        "https://gamebanana.com/mmdl/5,Mod",
        "https://gamebanana.com/mmdl/5,Tool,1",
        "https://gamebanana.com/mmdl/x,Mod,1",
        "",
        42,
        None,
    ],
)
def test_foreign_or_malformed_entries_are_dropped_before_any_request(service, entry):
    with patch.object(remote_install_service.GameBananaAPI, "get_installable_mod") as lookup:
        service._queue(entry)

    lookup.assert_not_called()


def test_entry_for_a_file_the_mod_does_not_have_is_dropped(service):
    emitted = []
    service.mod_ready.connect(lambda *args: emitted.append(args))

    with patch.object(remote_install_service.GameBananaAPI, "get_installable_mod", return_value=_mod(1)):
        service._queue("https://gamebanana.com/mmdl/2,Mod,1")

    assert emitted == []


def test_a_dropped_entry_is_logged_by_its_type_and_never_by_its_text(service, caplog):
    with caplog.at_level(logging.WARNING):
        service._queue("https://evil.example.com/x.zip,Mod,1")
        service._queue(42)

    assert "entry of type str" in caplog.text
    assert "entry of type int" in caplog.text
    assert "evil.example.com" not in caplog.text


def test_a_failed_lookup_is_logged_by_mod_and_file_id(service, caplog):
    with (
        caplog.at_level(logging.WARNING),
        patch.object(remote_install_service.GameBananaAPI, "get_installable_mod", return_value=_mod(1)),
    ):
        service._queue("https://gamebanana.com/mmdl/9001,Wip,111")

    assert "could not queue wip 111, file 9001" in caplog.text
    assert "gamebanana.com" not in caplog.text


def test_one_broken_entry_does_not_stop_the_rest(service):
    emitted = []
    service.mod_ready.connect(lambda mod, file: emitted.append(file))
    lookups = [RuntimeError("gone"), _mod(2)]

    with (
        patch.object(remote_install_service, "get_session") as session,
        patch.object(remote_install_service.GameBananaAPI, "get_installable_mod", side_effect=lookups),
    ):
        session.return_value.get.return_value = _reply(payload=["https://gamebanana.com/mmdl/1,Mod,1", "https://gamebanana.com/mmdl/2,Mod,2"])
        service._busy = True
        service._fetch(CREDENTIALS)

    assert emitted == [{"id": 2}]
    assert not service._busy


def test_poll_asks_the_member_queue_of_every_app_id(service, monkeypatch):
    monkeypatch.setattr(remote_install_service, "APP_IDS", ("G3M", "GameMakerModManager"))
    with patch.object(remote_install_service, "get_session") as session:
        session.return_value.get.return_value = _reply()
        service._fetch(CREDENTIALS)

    urls = [call.args[0] for call in session.return_value.get.call_args_list]
    assert [url.rsplit("/", 4)[1:] for url in urls] == [
        ["RemoteInstall", "4242", "TopSecret", "G3M"],
        ["RemoteInstall", "4242", "TopSecret", "GameMakerModManager"],
    ]


def test_a_rejected_app_id_does_not_stop_the_other_queue(service, monkeypatch):
    monkeypatch.setattr(remote_install_service, "APP_IDS", ("G3M", "GameMakerModManager"))
    emitted = []
    service.mod_ready.connect(lambda mod, file: emitted.append(file))
    service._timer.start()
    replies = {
        "G3M": _reply(status=404),
        "GameMakerModManager": _reply(payload=["https://gamebanana.com/mmdl/9001,Mod,111"]),
    }

    with (
        patch.object(remote_install_service, "get_session") as session,
        patch.object(remote_install_service.GameBananaAPI, "get_installable_mod", return_value=_mod(9001)),
    ):
        session.return_value.get.side_effect = lambda url, **_: replies[url.rsplit("/", 1)[1]]
        service._fetch(CREDENTIALS)
        session.return_value.get.reset_mock()
        service._fetch(CREDENTIALS)

    assert emitted == [{"id": 9001}, {"id": 9001}]
    assert service._rejected == {"G3M"}
    assert service._timer.isActive()
    assert [call.args[0].rsplit("/", 1)[1] for call in session.return_value.get.call_args_list] == ["GameMakerModManager"]
    service._timer.stop()


def test_rejected_key_stops_the_polling(service):
    service._timer.start()
    with patch.object(remote_install_service, "get_session") as session:
        session.return_value.get.return_value = _reply(status=404)
        service._fetch(CREDENTIALS)

    service.poll()

    assert service._rejected == {"G3M"}
    assert not service._timer.isActive()


def test_server_error_keeps_polling(service):
    with patch.object(remote_install_service, "get_session") as session:
        session.return_value.get.return_value = _reply(status=503)
        service._fetch(CREDENTIALS)

    assert not service._rejected


def test_secret_key_never_reaches_the_log(service, caplog):
    with patch.object(remote_install_service, "get_session") as session, caplog.at_level(logging.DEBUG):
        session.return_value.get.side_effect = RuntimeError(f"failed for {CREDENTIALS['secret_key']}")
        service._fetch(CREDENTIALS)

    assert caplog.records
    assert "TopSecret" not in caplog.text


def test_unpaired_service_does_not_poll(service):
    service.app_state.local_config = {}
    with patch.object(remote_install_service.threading, "Thread") as thread:
        service.start()
        service.poll()

    thread.assert_not_called()


def test_refresh_polls_now_restarts_the_interval_and_retries_a_rejected_key(service):
    service._rejected = {"G3M"}
    service._timer.start()

    with patch.object(service, "poll") as poll:
        service.refresh()

    poll.assert_called_once()
    assert not service._rejected
    assert service._timer.isActive()
    service._timer.stop()


def test_refresh_without_pairing_does_nothing(service):
    service.app_state.local_config = {}
    with patch.object(service, "poll") as poll:
        service.refresh()

    poll.assert_not_called()


def test_repairing_to_another_account_ignores_the_old_accounts_answer(service):
    emitted = []
    service.mod_ready.connect(lambda mod, file: emitted.append(file))
    old = service.app_state.local_config[CONFIG_KEY]

    with patch.object(remote_install_service, "get_session") as session, patch.object(service, "start"):
        session.return_value.get.side_effect = lambda *a, **k: (
            service.pair("7", "other"),
            _reply(status=404),
        )[1]
        service._busy = True
        service._fetch(old)

    assert not service._rejected
    assert not emitted
    assert service.app_state.local_config[CONFIG_KEY] == {"member_id": "7", "secret_key": "other"}
    assert not service._busy


def test_repairing_the_same_account_keeps_the_running_poll(service):
    service._busy = True

    with patch.object(service, "start"):
        service.pair(CREDENTIALS["member_id"], CREDENTIALS["secret_key"])

    assert service._busy


def test_pairing_back_to_the_first_account_does_not_revive_its_old_poll(service):
    first = service.app_state.local_config[CONFIG_KEY]
    service._busy = True

    with patch.object(service, "start"):
        service.pair("7", "other")
        service.pair(first["member_id"], first["secret_key"])
        service._busy = True  # the poll started for the second pairing is running
        with patch.object(remote_install_service, "get_session") as session:
            session.return_value.get.return_value = _reply()
            service._fetch(first)

    assert service._busy
