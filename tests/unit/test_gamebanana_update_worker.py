from workers.gamebanana.update_worker import ResolveGameBananaUpdatesThread


def _file(file_id, version, timestamp=0):
    return {"metadata": {"gb_file_id": file_id, "timestamp": timestamp, "version": version}}


def test_gamebanana_update_worker_ignores_the_same_version_in_any_package():
    candidate = {"file_id": 10, "file_timestamp": 10, "version": "1.0"}

    assert not ResolveGameBananaUpdatesThread._is_newer(candidate, _file(11, "1.0.0", 20))
    assert ResolveGameBananaUpdatesThread._newer_resolutions(
        candidate, [_file(12, "1.0", 30), _file(13, "1.0", 40)]
    ) == []


def test_gamebanana_update_worker_uses_version_without_file_marker():
    assert ResolveGameBananaUpdatesThread._is_newer({"version": "1.0.0"}, _file(11, "2.0.0"))


def test_gamebanana_update_worker_offers_every_file_of_a_newer_release():
    candidate = {"file_id": 10, "file_timestamp": 100, "version": "0.1.1"}
    files = [_file(i, "0.1.2", 200 + i) for i in (11, 12)]

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, files) == files


def test_gamebanana_update_worker_offers_only_higher_versions():
    candidate = {"file_id": 10, "file_timestamp": 100, "version": "1.0"}
    older, newer = _file(11, "0.9", 300), _file(12, "1.1", 5)

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, [older, newer]) == [newer]


def test_gamebanana_update_worker_recovers_missing_timestamp_when_versions_are_unset():
    candidate = {"file_id": 10}
    sibling = _file(11, "", 20)

    assert ResolveGameBananaUpdatesThread._newer_resolutions(
        candidate, [_file(10, "", 10), sibling]
    ) == [sibling]
    assert "file_timestamp" not in candidate
