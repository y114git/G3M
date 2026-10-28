from workers.gamebanana.update_worker import ResolveGameBananaUpdatesThread


def test_gamebanana_update_worker_ignores_another_file_at_the_same_version():
    candidate = {"file_id": 10, "version": "1.0.0"}
    resolved = {"metadata": {"gb_file_id": 11, "version": "1.0.0"}}

    assert not ResolveGameBananaUpdatesThread._is_newer(candidate, resolved)


def test_gamebanana_update_worker_uses_version_without_file_marker():
    candidate = {"version": "1.0.0"}
    resolved = {"metadata": {"gb_file_id": 11, "version": "2.0.0"}}

    assert ResolveGameBananaUpdatesThread._is_newer(candidate, resolved)


def test_gamebanana_update_worker_uses_newer_same_version_upload():
    candidate = {"file_id": 10, "file_timestamp": 10, "version": "1.0"}
    resolved = {
        "metadata": {"gb_file_id": 11, "timestamp": 20, "version": "1.0.0"}
    }

    assert ResolveGameBananaUpdatesThread._is_newer(candidate, resolved)


def test_gamebanana_update_worker_exposes_only_newer_files():
    candidate = {"file_id": 10, "file_timestamp": 10, "version": "1.0"}
    older = {"metadata": {"gb_file_id": 11, "timestamp": 5, "version": "1.0"}}
    newer = {"metadata": {"gb_file_id": 12, "timestamp": 20, "version": "1.0"}}

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, [older, newer]) == [newer]


def test_gamebanana_update_worker_recovers_missing_timestamp_from_installed_upload():
    candidate = {"file_id": 10, "version": "1.0"}
    installed = {"metadata": {"gb_file_id": 10, "timestamp": 10, "version": "1.0"}}
    sibling = {"metadata": {"gb_file_id": 11, "timestamp": 20, "version": "1.0"}}

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, [sibling, installed]) == []
    assert "file_timestamp" not in candidate


def test_gamebanana_update_worker_does_not_offer_the_other_package_of_the_installed_release():
    candidate = {"file_id": 10, "file_timestamp": 100, "version": "0.1.2"}
    installed = {"metadata": {"gb_file_id": 10, "timestamp": 100, "version": "0.1.2"}}
    sibling = {"metadata": {"gb_file_id": 11, "timestamp": 150, "version": "0.1.2"}}

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, [installed, sibling]) == []


def test_gamebanana_update_worker_offers_a_replacement_when_the_installed_file_is_gone():
    candidate = {"file_id": 10, "file_timestamp": 100, "version": "0.1.2"}
    replacement = {"metadata": {"gb_file_id": 12, "timestamp": 150, "version": "0.1.2"}}
    sibling = {"metadata": {"gb_file_id": 13, "timestamp": 160, "version": "0.1.2"}}

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, [replacement, sibling]) == [replacement, sibling]


def test_gamebanana_update_worker_offers_every_file_of_a_newer_release():
    candidate = {"file_id": 10, "file_timestamp": 100, "version": "0.1.1"}
    files = [{"metadata": {"gb_file_id": i, "timestamp": 200 + i, "version": "0.1.2"}} for i in (11, 12)]

    assert ResolveGameBananaUpdatesThread._newer_resolutions(candidate, files) == files

