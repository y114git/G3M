from unittest.mock import Mock, patch


class TestAnnounceService:
    """Tests for announce service."""
    def test_get_poll_options_returns_arbitrary_named_children(self, app_state):
        """Checks that getting poll options returns arbitrary named children."""
        from services.announce_service import AnnounceService

        service = AnnounceService(app_state, Mock())

        options = service.get_poll_options(
            {
                "type": "poll_multiple",
                "poll": {
                    "A": {},
                    "Option B": {},
                    "_meta": {"ignored": True},
                    "C": 3,
                },
            }
        )

        assert options == ["A", "Option B", "C"]

    def test_submit_poll_vote_creates_identity_and_persists_vote(self, app_state):
        """Checks that submitting poll vote creates identity and persists vote."""
        from services.announce_service import AnnounceService

        settings_service = Mock()
        service = AnnounceService(app_state, settings_service)
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True}

        with patch(
            "services.announce_service.CLOUD_FUNCTIONS_BASE_URL",
            "https://example.com",
        ), patch("services.announce_service.get_session") as get_session_mock:
            get_session_mock.return_value.post.return_value = response
            success, error = service.submit_poll_vote(
                {
                    "version": 7,
                    "type": "poll_single",
                    "poll": {"A": {}, "B": {}},
                },
                ["A"],
            )

        assert success is True
        assert error == ""
        assert app_state.local_config["announce_identity"]
        assert app_state.local_config["announce_poll_votes"]["7"]["selected_options"] == ["A"]
        assert settings_service.write_local_config.call_count >= 2
