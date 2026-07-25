"""Runtime registry for built-in and custom games."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, pyqtSignal

from models.game_modes import (
    BUILTIN_GAME_REGISTRY,
    CustomGameRecord,
    CustomSingleTabGame,
    GameEntry,
    get_first_visible_game_id,
    replace_game_entries,
)
from utils.time_utils import utc_now_iso

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class GameRegistryValidationError(ValueError):
    """Validation error with a stable translation key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass
class GameRegistryState:
    """Persisted registry state."""

    schema_version: int = 1
    order: list[str] = field(default_factory=list)
    visibility: dict[str, bool] = field(default_factory=dict)
    custom_games: list[CustomGameRecord] = field(default_factory=list)


class GameRegistryService(QObject):
    """Loads, validates, persists, and publishes runtime game entries."""

    games_changed = pyqtSignal()

    def __init__(self, app_state, settings_service, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.settings_service = settings_service
        self.state = GameRegistryState(order=list(BUILTIN_GAME_REGISTRY))
        self._state_path = Path(app_state.config_dir) / "custom_games.json"

    def load(self) -> None:
        self.state = self._read_state()
        self._publish()

    def list_manager_games(self) -> list[GameEntry]:
        from models.game_modes import get_manager_game_entries

        return get_manager_game_entries()

    def list_visible_games(self) -> list[GameEntry]:
        from models.game_modes import get_visible_game_entries

        return get_visible_game_entries()

    def list_search_games(self) -> list[GameEntry]:
        from models.game_modes import get_search_game_entries

        return get_search_game_entries()

    def create_custom_game(
        self,
        display_name: str,
        primary_executable: str,
        data_file_name: str,
        steam_app_id: str = "",
        gamebanana_id: str = "",
    ) -> CustomGameRecord:
        record = CustomGameRecord(
            id=self._generate_custom_id(display_name),
            display_name=display_name.strip(),
            primary_executable=self._validate_executable(primary_executable),
            data_file_name=self._validate_data_file_name(data_file_name),
            steam_app_id=self._validate_numeric_id(
                steam_app_id, "games.validation_steam_id"
            ),
            gamebanana_id=self._validate_gamebanana_id(gamebanana_id),
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        self._validate_record(record)
        self.state.custom_games.append(record)
        self.state.order.append(record.id)
        self.state.visibility.setdefault(record.id, True)
        self._save_and_publish()
        return record

    def update_custom_game(
        self,
        game_id: str,
        display_name: str,
        primary_executable: str,
        data_file_name: str,
        steam_app_id: str = "",
        gamebanana_id: str = "",
    ) -> CustomGameRecord:
        record = self._find_custom_game(game_id)
        updated = CustomGameRecord(
            id=record.id,
            display_name=display_name.strip(),
            primary_executable=self._validate_executable(primary_executable),
            data_file_name=self._validate_data_file_name(data_file_name),
            steam_app_id=self._validate_numeric_id(
                steam_app_id, "games.validation_steam_id"
            ),
            gamebanana_id=self._validate_gamebanana_id(gamebanana_id),
            created_at=record.created_at,
            updated_at=utc_now_iso(),
        )
        self._validate_record(updated, editing_id=game_id)
        self.state.custom_games = [
            updated if item.id == game_id else item for item in self.state.custom_games
        ]
        self._save_and_publish()
        return updated

    def delete_custom_game(self, game_id: str) -> None:
        self._find_custom_game(game_id)
        self.state.custom_games = [
            record for record in self.state.custom_games if record.id != game_id
        ]
        self.state.order = [
            item_id for item_id in self.state.order if item_id != game_id
        ]
        self.state.visibility.pop(game_id, None)
        self._save_and_publish()

    def reorder(self, ordered_ids: list[str]) -> None:
        known_ids = {entry.id for entry in self.list_manager_games()}
        normalized = [game_id for game_id in ordered_ids if game_id in known_ids]
        normalized.extend(
            game_id
            for game_id in self.state.order
            if game_id in known_ids and game_id not in normalized
        )
        normalized.extend(game_id for game_id in known_ids if game_id not in normalized)
        self.state.order = normalized
        self._save_and_publish()

    def set_visibility(self, game_id: str, visible: bool) -> None:
        if not visible:
            visible_ids = {entry.id for entry in self.list_visible_games()}
            if game_id in visible_ids and len(visible_ids) <= 1:
                raise GameRegistryValidationError("games.validation_last_visible")
        self.state.visibility[game_id] = bool(visible)
        self._save_and_publish()

    def is_visible(self, game_id: str) -> bool:
        return self.state.visibility.get(game_id, True)

    def get_custom_game(self, game_id: str) -> CustomGameRecord | None:
        return next(
            (record for record in self.state.custom_games if record.id == game_id), None
        )

    def ensure_valid_game_id(self, game_id: str) -> str:
        visible_ids = {entry.id for entry in self.list_visible_games()}
        return game_id if game_id in visible_ids else get_first_visible_game_id()

    def _save_and_publish(self) -> None:
        self._write_state()
        self._publish()

    def _publish(self) -> None:
        replace_game_entries(self._build_entries())
        self.games_changed.emit()

    def _build_entries(self) -> list[GameEntry]:
        custom_map = {
            record.id: CustomSingleTabGame(record) for record in self.state.custom_games
        }
        definitions = dict(BUILTIN_GAME_REGISTRY) | custom_map
        order = [game_id for game_id in self.state.order if game_id in definitions]
        order.extend(
            game_id for game_id in BUILTIN_GAME_REGISTRY if game_id not in order
        )
        order.extend(
            record.id for record in self.state.custom_games if record.id not in order
        )
        return [
            GameEntry(
                id=game_id,
                is_builtin=game_id in BUILTIN_GAME_REGISTRY,
                is_visible=self.state.visibility.get(game_id, True),
                sort_index=index,
                game_definition=definitions[game_id],
            )
            for index, game_id in enumerate(order)
        ]

    def _read_state(self) -> GameRegistryState:
        data = self.settings_service.read_json(str(self._state_path)) or {}
        custom_games = [
            CustomGameRecord(
                id=str(item.get("id", "")).strip(),
                display_name=str(item.get("display_name", "")).strip(),
                primary_executable=str(item.get("primary_executable", "")).strip(),
                data_file_name=self._read_data_file_name(item),
                steam_app_id=str(item.get("steam_app_id", "") or "").strip() or None,
                gamebanana_id=int(item["gamebanana_id"])
                if str(item.get("gamebanana_id", "")).strip().isdigit()
                else None,
                created_at=str(item.get("created_at", "")),
                updated_at=str(item.get("updated_at", "")),
            )
            for item in data.get("custom_games", [])
            if str(item.get("id", "")).strip()
        ]
        state = GameRegistryState(
            schema_version=int(data.get("schema_version", 1) or 1),
            order=[
                str(item).strip() for item in data.get("order", []) if str(item).strip()
            ],
            visibility={
                str(k).strip(): bool(v)
                for k, v in (data.get("visibility", {}) or {}).items()
                if str(k).strip()
            },
            custom_games=custom_games,
        )
        if not state.order:
            state.order = list(BUILTIN_GAME_REGISTRY)
        for game_id in BUILTIN_GAME_REGISTRY:
            state.visibility.setdefault(game_id, True)
        for record in state.custom_games:
            state.visibility.setdefault(record.id, True)
        return state

    def _write_state(self) -> None:
        payload = {
            "schema_version": self.state.schema_version,
            "order": self.state.order,
            "visibility": self.state.visibility,
            "custom_games": [asdict(record) for record in self.state.custom_games],
        }
        self.settings_service.write_json(str(self._state_path), payload)

    def _find_custom_game(self, game_id: str) -> CustomGameRecord:
        for record in self.state.custom_games:
            if record.id == game_id:
                return record
        raise GameRegistryValidationError("games.validation_not_custom")

    def _validate_record(
        self, record: CustomGameRecord, editing_id: str | None = None
    ) -> None:
        if not record.display_name:
            raise GameRegistryValidationError("games.validation_name_required")
        used_names = {
            entry.display_name.casefold()
            for entry in self.list_manager_games()
            if entry.id != editing_id
        }
        if record.display_name.casefold() in used_names:
            raise GameRegistryValidationError("games.validation_name_unique")
        used_steam = {
            entry.steam_app_id
            for entry in self.list_manager_games()
            if entry.id != editing_id and entry.steam_app_id
        }
        if record.steam_app_id and record.steam_app_id in used_steam:
            raise GameRegistryValidationError("games.validation_steam_unique")
        used_gamebanana = {
            entry.gamebanana_id
            for entry in self.list_manager_games()
            if entry.id != editing_id and entry.gamebanana_id
        }
        if record.gamebanana_id and record.gamebanana_id in used_gamebanana:
            raise GameRegistryValidationError("games.validation_gamebanana_unique")

    def _generate_custom_id(self, display_name: str) -> str:
        base = _SLUG_RE.sub("_", display_name.strip().casefold()).strip("_") or "game"
        candidate = f"custom_{base}"
        taken = {entry.id for entry in self.list_manager_games()}
        suffix = 2
        while candidate in taken:
            candidate = f"custom_{base}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _validate_executable(value: str) -> str:
        result = value.strip()
        if not result:
            raise GameRegistryValidationError("games.validation_executable_required")
        if "/" in result or "\\" in result:
            raise GameRegistryValidationError("games.validation_executable_name_only")
        return result

    @staticmethod
    def _validate_data_file_name(value: str) -> str:
        result = value.strip()
        if not result:
            raise GameRegistryValidationError("games.validation_data_file_required")
        if "/" in result or "\\" in result:
            raise GameRegistryValidationError("games.validation_data_file_name_only")
        return result

    @staticmethod
    def _validate_numeric_id(value: str, error_key: str) -> str | None:
        result = value.strip()
        if not result:
            return None
        if not result.isdigit():
            raise GameRegistryValidationError(error_key)
        return result

    def _validate_gamebanana_id(self, value: str) -> int | None:
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.isdigit():
            return int(candidate)
        parsed = urlparse(candidate)
        match = re.fullmatch(r"/games/(\d+)/?", parsed.path)
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"gamebanana.com", "www.gamebanana.com"}
            and match
        ):
            return int(match.group(1))
        raise GameRegistryValidationError("games.validation_gamebanana_id")

    @staticmethod
    def _read_data_file_name(item: dict) -> str:
        value = str(item.get("data_file_name", "")).strip()
        if value:
            return value
        primary_executable = str(item.get("primary_executable", "")).strip().lower()
        if primary_executable.endswith(".app"):
            return "game.ios"
        if primary_executable and not primary_executable.endswith(".exe"):
            return "game.unx"
        return "data.win"
