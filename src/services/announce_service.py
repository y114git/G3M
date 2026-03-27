"""Announcement and poll helpers."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Iterable

from config.config import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_SHORT
from utils.network_utils import get_session

_ANNOUNCE_TYPE_POST = "post"
_ANNOUNCE_TYPE_POLL_SINGLE = "poll_single"
_ANNOUNCE_TYPE_POLL_MULTIPLE = "poll_multiple"
_VALID_ANNOUNCE_TYPES = {
    _ANNOUNCE_TYPE_POST,
    _ANNOUNCE_TYPE_POLL_SINGLE,
    _ANNOUNCE_TYPE_POLL_MULTIPLE,
}


class AnnounceService:
    """Coordinates announce payload parsing and poll submissions."""

    _IDENTITY_KEY = "announce_identity"

    def __init__(self, app_state, settings_service) -> None:
        self.app_state = app_state
        self.settings_service = settings_service

    @staticmethod
    def get_announce_type(announce: dict | None) -> str:
        announce_type = str((announce or {}).get("type") or _ANNOUNCE_TYPE_POST).strip()
        return announce_type if announce_type in _VALID_ANNOUNCE_TYPES else _ANNOUNCE_TYPE_POST

    @classmethod
    def is_poll_announce(cls, announce: dict | None) -> bool:
        return cls.get_announce_type(announce) in {
            _ANNOUNCE_TYPE_POLL_SINGLE,
            _ANNOUNCE_TYPE_POLL_MULTIPLE,
        }

    @classmethod
    def allows_multiple_selection(cls, announce: dict | None) -> bool:
        return cls.get_announce_type(announce) == _ANNOUNCE_TYPE_POLL_MULTIPLE

    @staticmethod
    def get_poll_options(announce: dict | None) -> list[str]:
        poll = (announce or {}).get("poll")
        if not poll:
            return []

        options: list[str] = []

        if isinstance(poll, list):
            for item in poll:
                if isinstance(item, str):
                    option_name = item.strip()
                    if option_name and not option_name.startswith("_"):
                        options.append(option_name)
                elif isinstance(item, dict) and "name" in item:
                    option_name = str(item["name"]).strip()
                    if option_name and not option_name.startswith("_"):
                        options.append(option_name)
            return options

        if not isinstance(poll, dict):
            return []

        order_key = None
        for key in ("order", "_order"):
            if key in poll and isinstance(poll[key], list):
                order_key = key
                break

        if order_key:
            order_list = poll[order_key]
            for key in order_list:
                if key in poll:
                    option_name = str(key).strip()
                    if option_name and not option_name.startswith("_"):
                        value = poll[key]
                        if isinstance(value, (dict, int, float, str)) or value is None:
                            options.append(option_name)
        else:
            for key, value in poll.items():
                option_name = str(key or "").strip()
                if not option_name or option_name.startswith("_"):
                    continue
                if isinstance(value, (dict, int, float, str)) or value is None:
                    options.append(option_name)

        return options

    def get_or_create_announce_identity(self) -> str:
        identity = str(self.app_state.local_config.get(self._IDENTITY_KEY, "")).strip()
        if identity:
            return identity
        identity = uuid.uuid4().hex
        self.app_state.local_config[self._IDENTITY_KEY] = identity
        self.settings_service.write_local_config()
        return identity

    def get_hashed_announce_identity(self) -> str:
        identity = self.get_or_create_announce_identity()
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def submit_poll_vote(
        self,
        announce: dict | None,
        selected_options: Iterable[str],
    ) -> tuple[bool, str]:
        normalized_options = [
            option
            for option in (str(item).strip() for item in selected_options)
            if option
        ]
        announce_type = self.get_announce_type(announce)
        if announce_type == _ANNOUNCE_TYPE_POLL_SINGLE and len(normalized_options) != 1:
            return False, "Please select exactly one option."
        if announce_type == _ANNOUNCE_TYPE_POLL_MULTIPLE and not normalized_options:
            return False, "Please select at least one option."
        try:
            version = int((announce or {}).get("version") or 0)
        except (ValueError, TypeError):
            return False, "Invalid announcement version."
        if version <= 0:
            return False, "Announcement version is missing."
        if not CLOUD_FUNCTIONS_BASE_URL:
            return False, "CLOUD_FUNCTIONS_BASE_URL is not configured."
        payload = {
            "announceVersion": version,
            "type": announce_type,
            "options": normalized_options,
            "clientId": self.get_hashed_announce_identity(),
            "timestamp": int(time.time()),
        }
        try:
            response = get_session(self.app_state).post(
                f"{CLOUD_FUNCTIONS_BASE_URL}/submitAnnouncePoll",
                json=payload,
                timeout=NETWORK_TIMEOUT_SHORT,
            )
        except Exception as exc:
            return False, str(exc)
        if response.status_code != 200:
            try:
                error_payload = response.json() or {}
            except Exception:
                error_payload = {}
            return False, str(error_payload.get("error") or f"HTTP {response.status_code}")
        self._persist_vote_submission(version, normalized_options)
        return True, ""

    def _persist_vote_submission(self, version: int, selected_options: list[str]) -> None:
        votes = self.app_state.local_config.get("announce_poll_votes")
        if not isinstance(votes, dict):
            votes = {}
        votes[str(version)] = {
            "selected_options": list(selected_options),
            "submitted_at": int(time.time()),
        }
        self.app_state.local_config["announce_poll_votes"] = votes
        self.settings_service.write_local_config()
