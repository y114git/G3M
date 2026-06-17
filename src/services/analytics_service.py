"""Lightweight aggregated analytics service."""

from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import json
import logging
import os
import platform
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

import requests
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from config.config import APP_VERSION, CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_SHORT
from ui.utils.ui_utils import safe_stop_thread
from utils.mod.utils import get_mod_id, get_mod_name, parse_gamebanana_mod_id
from utils.network_utils import cloud_function_request

logger = logging.getLogger(__name__)


class _AnalyticsUploadWorker(QObject):
    finished = pyqtSignal(bool, int)
    _REQUEST_TIMEOUT_SECONDS = min(2, NETWORK_TIMEOUT_SHORT)

    def __init__(self, batch: list[dict[str, Any]]) -> None:
        super().__init__()
        self._batch = batch

    def run(self) -> None:
        success = False
        session = None
        try:
            session = requests.Session()
            success = True
            payload = self._request_payload(self._batch)
            if not payload:
                success = False
            else:
                encoded = base64.b64encode(
                    gzip.compress(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8"),
                        compresslevel=9,
                    )
                ).decode("ascii")
                response = cloud_function_request(
                    "post",
                    f"{CLOUD_FUNCTIONS_BASE_URL}/sendAnalytics",
                    session=session,
                    json={"encoding": "gzip+base64", "payload": encoded},
                    timeout=self._REQUEST_TIMEOUT_SECONDS,
                )
                if not response or getattr(response, "status_code", 500) >= 300:
                    success = False
        except Exception as e:
            logger.debug("Analytics flush failed: %s", e, exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                if session is not None:
                    session.close()
        try:
            self.finished.emit(success, len(self._batch))
        except Exception as e:
            logger.warning(
                "Analytics upload worker failed to emit finished: %s",
                e,
                exc_info=True,
            )

    @staticmethod
    def _merge_batch(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(batch) == 1:
            return [batch[0]]
        groups: dict[str, list[dict[str, Any]]] = {}
        for payload in batch:
            if not isinstance(payload, dict):
                continue
            session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
            group_key = str(session.get("id") or payload.get("batch_id") or "")
            groups.setdefault(group_key, []).append(payload)
        merged: list[dict[str, Any]] = []
        for group in groups.values():
            always: list[dict[str, Any]] = []
            opt_in: list[dict[str, Any]] = []
            ids: list[str] = []
            client: dict[str, Any] = {}
            session: dict[str, Any] = {}
            for payload in group:
                ids.append(str(payload.get("batch_id") or ""))
                if not client and isinstance(payload.get("client"), dict):
                    client = payload["client"]
                if not session and isinstance(payload.get("session"), dict):
                    session = payload["session"]
                always.extend(payload.get("always") or [])
                opt_in.extend(payload.get("opt_in") or [])
            batch_id = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()[:32]
            merged.append(
                {
                    "schema": 1,
                    "batch_id": batch_id,
                    "sent_at": int(time.time()),
                    "client": client,
                    "session": session,
                    "always": always,
                    "opt_in": opt_in,
                }
            )
        return merged

    @classmethod
    def _request_payload(cls, batch: list[dict[str, Any]]) -> dict[str, Any] | None:
        merged = cls._merge_batch(batch)
        if not merged:
            return None
        if len(merged) == 1:
            return merged[0]
        return {
            "schema": 1,
            "sent_at": int(time.time()),
            "batches": merged,
        }


class AnalyticsService(QObject):
    """Aggregates cheap anonymous analytics and flushes compressed batches."""

    _MAX_DIM_LEN = 40
    _MAX_PENDING_PAYLOADS = 80
    _MAX_UNIQUE_ALWAYS = 256
    _MAX_UNIQUE_OPT_IN = 512
    _STATE_SAVE_DELAY_MS = 1500

    def __init__(self, app_state, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self._session_id = uuid.uuid4().hex
        self._always_on = Counter()
        self._opt_in = Counter()
        self._always_total = 0
        self._opt_total = 0
        self._pending: list[dict[str, Any]] = []
        self._download_states: dict[str, tuple[str, str, bool]] = {}
        self._active_searches = {"mods_browser": False, "library": False}
        self._session_started_at = time.monotonic()
        self._startup_started_at = time.monotonic()
        self._session_closed = False
        self._ui_ready_recorded = False
        self._window = None
        self._upload_thread = None
        self._upload_worker = None
        self._upload_batch_size = 0
        self._upload_in_flight: list[dict[str, Any]] = []
        self._shutdown_callbacks: list[Callable[[], None]] = []
        self._load_state()
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_async)
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._save_state)
        self.count("app_launch", os=self._os_key())
        self.count(
            "app_launch_detail",
            scope="opt_in",
            os=self._os_key(),
            locale=self._clean_value(self._local_config().get("language", "en")),
            py=self._clean_value(
                f"{sys.version_info.major}.{sys.version_info.minor}"
            ),
        )

    @property
    def opt_in_enabled(self) -> bool:
        return bool(self._local_config().get("analytics_opt_in_enabled", False))

    def set_opt_in_enabled(self, enabled: bool) -> None:
        previous = self.opt_in_enabled
        self._local_config()["analytics_opt_in_enabled"] = bool(enabled)
        if enabled and not previous:
            self.count("opt_in_enabled")
        if not enabled:
            self._opt_in.clear()
            self._opt_total = 0
            if self._upload_in_flight:
                stripped = []
                for payload in self._upload_in_flight:
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("always"):
                        stripped.append({**payload, "opt_in": []})
                self._upload_in_flight = stripped
            retained = []
            for payload in self._pending:
                if not isinstance(payload, dict):
                    continue
                if payload.get("always"):
                    retained.append({**payload, "opt_in": []})
            self._pending = retained[-self._MAX_PENDING_PAYLOADS :]
            self._schedule_state_save()

    def attach_window(self, window) -> None:
        if self._window is window:
            return
        self._window = window
        if hasattr(window, "main_tab_widget"):
            window.main_tab_widget.currentChanged.connect(self._on_tab_changed)
            QTimer.singleShot(
                0,
                lambda: self._on_tab_changed(window.main_tab_widget.currentIndex()),
            )
        self.app_state.search_text_changed.connect(
            lambda text: self._on_search_text_changed("mods_browser", text)
        )
        self.app_state.library_search_text_changed.connect(
            lambda text: self._on_search_text_changed("library", text)
        )
        if hasattr(window, "downloads_manager"):
            window.downloads_manager.record_added.connect(self._on_download_record_added)
            window.downloads_manager.record_updated.connect(
                self._on_download_record_updated
            )
        app = getattr(window, "instance", None)
        with contextlib.suppress(Exception):
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
        if app:
            with contextlib.suppress(Exception):
                app.aboutToQuit.connect(self.shutdown)

    def mark_ui_ready(self) -> None:
        if self._ui_ready_recorded:
            return
        self._ui_ready_recorded = True
        startup_bucket = self._bucket_seconds(
            time.monotonic() - self._startup_started_at
        )
        self.count("app_ready", startup=startup_bucket)
        self.count("app_ready_detail", scope="opt_in", startup=startup_bucket)

    def record_dialog_opened(self, name: str) -> None:
        clean_name = self._clean_value(name)
        self.count("dialog_opened", name=clean_name)
        self.count("dialog_opened_detail", scope="opt_in", name=clean_name)

    def record_profile_switched(self) -> None:
        self.count("profile_switched")
        self.count("profile_switched_detail", scope="opt_in")

    def record_action(self, event: str, *, detail_event: str | None = None, **dims) -> None:
        clean_dims = {self._clean_value(key): self._clean_value(value) for key, value in dims.items()}
        clean_dims = {key: value for key, value in clean_dims.items() if key and value}
        self.count(event, **clean_dims)
        self.count(detail_event or f"{event}_detail", scope="opt_in", **clean_dims)

    def record_setting_changed(self, name: str, enabled: bool) -> None:
        clean_name = self._clean_value(name)
        state = "on" if enabled else "off"
        self.count("setting_changed", name=clean_name, state=state)
        self.count(
            "setting_changed_detail",
            scope="opt_in",
            name=clean_name,
            state=state,
        )

    def record_mods_browser_search(self, query: str) -> None:
        bucket = self._mods_browser_query_length_bucket(query)
        self.count("search_mods_browser", area="mods_browser", query_len=bucket)
        self.count(
            "search_mods_browser_detail",
            scope="opt_in",
            area="mods_browser",
            query_len=bucket,
        )

    def record_mod_opened(self, area: str, mod=None) -> None:
        dims = {"area": area, **self._mod_common_dims(mod)}
        self.count("mod_opened", **dims)
        self._record_mod_detail("mod_opened_detail", "area", area, mod)

    def record_mod_details_opened(self, area: str, mod=None) -> None:
        dims = {"area": area, **self._mod_common_dims(mod)}
        self.count("mod_details_opened", **dims)
        self._record_mod_detail("mod_details_opened_detail", "area", area, mod)

    def record_mod_export_requested(self, mod=None) -> None:
        dims = self._mod_common_dims(mod)
        self.count("mod_export_requested", **dims)
        self._record_mod_detail("mod_export_requested_detail", "action", "export", mod)

    def record_mod_folder_opened(self, mod=None) -> None:
        dims = self._mod_common_dims(mod)
        self.count("mod_folder_opened", **dims)
        self._record_mod_detail("mod_folder_opened_detail", "action", "open_folder", mod)

    def record_mod_homepage_opened(self, mod=None) -> None:
        dims = self._mod_common_dims(mod)
        self.count("mod_homepage_opened", **dims)
        self._record_mod_detail(
            "mod_homepage_opened_detail",
            "action",
            "open_homepage",
            mod,
        )

    def record_launch_started(
        self,
        *,
        mode: str,
        with_mods: bool,
        game: str = "unknown",
        mod_count: int = 0,
        mod_refs: list[dict[str, str]] | None = None,
        via_steam: bool = False,
    ) -> None:
        dims = self._launch_dims(
            mode=mode,
            with_mods=with_mods,
            game=game,
            mod_count=mod_count,
            via_steam=via_steam,
        )
        self.count("game_launch_started", **dims)
        self.count("game_launch_started_detail", scope="opt_in", **dims)
        for payload in self._normalized_mod_refs(mod_refs):
            always_payload = {k: v for k, v in payload.items() if k != "name"}
            self.count("launch_mod_selected", game=dims["game"], **always_payload)
            self.count("launch_mod_selected_detail", scope="opt_in", game=dims["game"], **payload)

    def record_launch_finished(
        self,
        seconds: float,
        *,
        mode: str,
        with_mods: bool,
        game: str = "unknown",
        mod_count: int = 0,
        mod_refs: list[dict[str, str]] | None = None,
        via_steam: bool = False,
    ) -> None:
        dims = self._launch_dims(
            mode=mode,
            with_mods=with_mods,
            game=game,
            mod_count=mod_count,
            via_steam=via_steam,
        )
        self.record_timing("game_launch_finished", seconds, **dims)
        self.record_timing("game_launch_finished_detail", seconds, scope="opt_in", **dims)
        for payload in self._normalized_mod_refs(mod_refs):
            always_payload = {k: v for k, v in payload.items() if k != "name"}
            self.record_timing(
                "launch_mod_playtime",
                seconds,
                game=dims["game"],
                **always_payload,
            )
            self.record_timing(
                "launch_mod_playtime_detail",
                seconds,
                scope="opt_in",
                game=dims["game"],
                **payload,
            )

    def record_launch_failed(
        self,
        *,
        reason: str,
        mode: str,
        with_mods: bool,
        game: str = "unknown",
        mod_count: int = 0,
        via_steam: bool = False,
    ) -> None:
        dims = self._launch_dims(
            mode=mode,
            with_mods=with_mods,
            game=game,
            mod_count=mod_count,
            via_steam=via_steam,
        )
        self.count("game_launch_failed", reason=reason, **dims)
        self.count("game_launch_failed_detail", scope="opt_in", reason=reason, **dims)

    def record_update_check(self, outcome: str) -> None:
        clean_outcome = self._clean_value(outcome) or "unknown"
        self.count("update_check", outcome=clean_outcome)
        self.count("update_check_detail", scope="opt_in", outcome=clean_outcome)

    def record_mod_install_requested(self, mod, *, mode: str) -> None:
        dims = {"mode": self._clean_value(mode), **self._mod_common_dims(mod)}
        self.count("mod_install_requested", **dims)
        self._record_mod_detail("mod_install_requested_detail", "mode", mode, mod)

    def record_mod_install_completed(self, mod, *, mode: str) -> None:
        dims = {"mode": self._clean_value(mode), **self._mod_common_dims(mod)}
        self.count("mod_install_completed", **dims)
        self._record_mod_detail("mod_install_completed_detail", "mode", mode, mod)

    def record_mod_install_cancelled(self, mod, *, mode: str) -> None:
        dims = {"mode": self._clean_value(mode), **self._mod_common_dims(mod)}
        self.count("mod_install_cancelled", **dims)
        self._record_mod_detail("mod_install_cancelled_detail", "mode", mode, mod)

    def record_mod_install_failed(self, mod, *, mode: str) -> None:
        dims = {"mode": self._clean_value(mode), **self._mod_common_dims(mod)}
        self.count("mod_install_failed", **dims)
        self._record_mod_detail("mod_install_failed_detail", "mode", mode, mod)

    def record_mod_removed(self, mod, *, action: str) -> None:
        dims = {"action": self._clean_value(action), **self._mod_common_dims(mod)}
        self.count("mod_removed", **dims)
        self._record_mod_detail("mod_removed_detail", "action", action, mod)

    def record_plugin_download_requested(self, entry) -> None:
        self.count("plugin_download_requested", source="catalog")
        self._record_plugin_detail(
            "plugin_download_requested_detail",
            entry,
            source="catalog",
        )

    def record_plugin_details_opened(self, entry) -> None:
        self.count("plugin_details_opened")
        self._record_plugin_detail(
            "plugin_details_opened_detail",
            entry,
            source="catalog",
        )

    def record_plugin_imported(self, *, source: str = "manual") -> None:
        clean_source = self._clean_value(source) or "manual"
        self.count("plugin_imported", source=clean_source)
        self.count("plugin_imported_detail", scope="opt_in", source=clean_source)

    def record_plugin_state_changed(
        self,
        *,
        plugin_id: str,
        plugin_name: str | None = None,
        version: str | None = None,
        enabled: bool,
        source: str = "installed",
    ) -> None:
        event = "plugin_enabled" if enabled else "plugin_disabled"
        clean_source = self._clean_value(source) or "installed"
        self.count(event, source=clean_source)
        self._record_plugin_detail(
            f"{event}_detail",
            {
                "id": plugin_id,
                "name": plugin_name,
                "version": version,
                "source": clean_source,
            },
            source=clean_source,
        )

    def record_plugin_deleted(
        self,
        *,
        plugin_id: str,
        plugin_name: str | None = None,
        version: str | None = None,
        source: str = "installed",
    ) -> None:
        clean_source = self._clean_value(source) or "installed"
        self.count("plugin_deleted", source=clean_source)
        self._record_plugin_detail(
            "plugin_deleted_detail",
            {
                "id": plugin_id,
                "name": plugin_name,
                "version": version,
                "source": clean_source,
            },
            source=clean_source,
        )

    def record_local_import(
        self,
        *,
        source: str,
        outcome: str,
        file_ext: str = "",
        merged: bool = False,
        manual: bool = False,
    ) -> None:
        dims = {
            "source": self._clean_value(source) or "file",
            "outcome": self._clean_value(outcome) or "unknown",
            "merged": "yes" if merged else "no",
            "manual": "yes" if manual else "no",
        }
        if file_ext:
            dims["ext"] = self._clean_value(file_ext)
        self.count("local_import", **dims)
        self.count("local_import_detail", scope="opt_in", **dims)

    def count(self, event: str, scope: str = "always", value: int = 1, **dims) -> None:
        if value <= 0:
            return
        if scope == "opt_in" and not self.opt_in_enabled:
            return
        counter, total_attr, max_unique = (
            (self._opt_in, "_opt_total", self._MAX_UNIQUE_OPT_IN)
            if scope == "opt_in"
            else (self._always_on, "_always_total", self._MAX_UNIQUE_ALWAYS)
        )
        key = self._event_key(event, dims)
        if key not in counter and len(counter) >= max_unique:
            key = self._event_key(f"{event}_overflow", {})
        counter[key] += int(value)
        setattr(self, total_attr, getattr(self, total_attr) + int(value))
        self._schedule_state_save()

    def record_timing(
        self, event: str, seconds: float, scope: str = "always", **dims
    ) -> None:
        dims = dict(dims)
        dims["duration_bucket"] = self._bucket_seconds(seconds)
        self.count(event, scope=scope, **dims)

    def shutdown(self) -> None:
        if self._session_closed:
            return
        self._session_closed = True
        self._record_session_end()
        self._enqueue_session_payload()
        self._flush_async(force=True)
        self._wait_for_upload_shutdown()

    def shutdown_async(self, on_finished=None) -> bool:
        if on_finished is not None:
            self._shutdown_callbacks.append(on_finished)
        if not self._session_closed:
            self._session_closed = True
            self._record_session_end()
            self._enqueue_session_payload()
        self._flush_async(force=True)
        self._notify_shutdown_complete_if_idle()
        return self._upload_thread is None and not self._pending

    def flush(self, force: bool = False) -> bool:
        self._flush_async(force=force)
        return not self._pending and self._upload_thread is None

    def _flush_async(self, force: bool = False) -> None:
        if not force:
            self._flush_timer.stop()
            self._enqueue_session_payload()
            self._save_state()
            return
        if self._always_on or self._opt_in:
            self._enqueue_session_payload(transient=True)
        if self._upload_thread or not self._pending:
            self._save_state()
            return
        batch = self._pending[:20]
        thread = QThread(self)
        worker = _AnalyticsUploadWorker(batch)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda success, size, upload_thread=thread: self._on_upload_finished(
                success, size, upload_thread
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda upload_thread=thread: self._on_upload_thread_finished(upload_thread)
        )
        self._upload_in_flight = list(batch)
        self._upload_batch_size = len(batch)
        self._upload_thread = thread
        self._upload_worker = worker
        self._save_state()
        thread.start()

    def _on_upload_finished(
        self, success: bool, batch_size: int, upload_thread: QThread
    ) -> None:
        in_flight = list(self._upload_in_flight)
        if success and in_flight:
            remaining_pending = list(self._pending)
            for payload in in_flight:
                with contextlib.suppress(ValueError):
                    remaining_pending.remove(payload)
            self._pending = remaining_pending
        self._upload_worker = None
        self._upload_batch_size = 0
        self._upload_in_flight = []
        self._save_state()
        if self._upload_thread is not upload_thread:
            return

    def _on_upload_thread_finished(self, upload_thread: QThread) -> None:
        if self._upload_thread is not upload_thread:
            return
        self._upload_thread = None
        self._save_state()
        self._notify_shutdown_complete_if_idle()

    def _schedule_state_save(self) -> None:
        self._state_timer.start(self._STATE_SAVE_DELAY_MS)

    def _record_session_end(self) -> None:
        config = self._local_config()
        duration = time.monotonic() - self._session_started_at
        self.count("session_end", duration=self._bucket_seconds(duration))
        self.count(
            "session_end_detail",
            scope="opt_in",
            duration=self._bucket_seconds(duration),
            locale=self._clean_value(config.get("language", "en")),
            scale=self._clean_value(
                int(float(config.get("ui_scale", 1.0)) * 100)
            ),
            theme=self._clean_value(
                "custom"
                if any(
                    config.get(k)
                    for k in (
                        "custom_background_color",
                        "custom_elements_color",
                        "custom_border_color",
                        "custom_hover_color",
                        "custom_select_color",
                        "custom_main_text_color",
                        "custom_secondary_text_color",
                    )
                )
                else "default"
            ),
        )

    def _notify_shutdown_complete_if_idle(self) -> None:
        if self._upload_thread is not None or self._pending:
            return
        callbacks = self._shutdown_callbacks[:]
        self._shutdown_callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.debug(
                    "Analytics shutdown callback failed: %s", e, exc_info=True
                )

    def _wait_for_upload_shutdown(self, timeout_ms: int = 1500) -> None:
        """Drain the final upload thread so QObject shutdown does not race Qt teardown."""
        thread = self._upload_thread
        if thread is None:
            return
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        app = QApplication.instance()
        while self._upload_thread is thread and time.monotonic() < deadline:
            if app is not None:
                with contextlib.suppress(Exception):
                    app.processEvents()
            if thread.wait(25):
                if app is not None:
                    with contextlib.suppress(Exception):
                        app.processEvents()
                break
        if self._upload_thread is thread and thread.isRunning():
            safe_stop_thread(thread, timeout=750, blocking=True)
            if app is not None:
                with contextlib.suppress(Exception):
                    app.processEvents()
        elif self._upload_thread is thread and not thread.isRunning():
            self._on_upload_thread_finished(thread)

    def _enqueue_session_payload(self, transient: bool = False) -> None:
        if not self._always_on and not self._opt_in:
            return
        payload = self._build_payload(
            dict(self._always_on),
            dict(self._opt_in),
        )
        self._always_on.clear()
        self._opt_in.clear()
        self._always_total = 0
        self._opt_total = 0
        self._pending.append(payload)
        self._pending = self._pending[-self._MAX_PENDING_PAYLOADS :]
        if not transient:
            self._save_state()

    def _build_payload(
        self,
        always_on: dict[str, int],
        opt_in: dict[str, int],
    ) -> dict[str, Any]:
        payload = {
            "schema": 1,
            "sent_at": int(time.time()),
            "client": self._client_payload(),
            "session": {
                "id": self._session_id,
                "opt_in": self.opt_in_enabled,
                "started_at": int(time.time() - (time.monotonic() - self._session_started_at)),
            },
            "always": self._counter_events(always_on),
            "opt_in": self._counter_events(opt_in),
        }
        payload["batch_id"] = self._payload_id(payload)
        return payload

    def _load_state(self) -> None:
        self._pending = []
        self._always_on = Counter()
        self._opt_in = Counter()
        self._always_total = 0
        self._opt_total = 0
        path = self._state_path()
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            pending = payload.get("pending") if isinstance(payload, dict) else []
            if isinstance(pending, list):
                valid_pending = [
                    item
                    for item in pending
                    if isinstance(item, dict) and item.get("schema") == 1
                ]
                self._pending = valid_pending[-self._MAX_PENDING_PAYLOADS :]
        except (OSError, json.JSONDecodeError, TypeError):
            self._pending = []

    def _save_state(self) -> None:
        self._state_timer.stop()
        path = self._state_path(create_parent=True)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {"schema": 1, "pending": self._pending[-self._MAX_PENDING_PAYLOADS :]},
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        except OSError as e:
            logger.debug("Analytics state save failed: %s", e, exc_info=True)

    def _state_path(self, *, create_parent: bool = False) -> str:
        config_dir = getattr(self.app_state, "config_dir", None)
        if not config_dir:
            return ""
        if create_parent:
            with contextlib.suppress(OSError):
                os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "analytics_pending.json")

    def _local_config(self) -> dict[str, Any]:
        config = getattr(self.app_state, "local_config", None)
        if isinstance(config, dict):
            return config
        config = {}
        with contextlib.suppress(Exception):
            self.app_state.local_config = config
        return config

    def _event_key(self, event: str, dims: dict[str, Any]) -> str:
        parts = [self._clean_value(event)]
        for key, value in sorted(dims.items()):
            clean = self._clean_value(value)
            if clean:
                parts.append(f"{self._clean_value(key)}={clean}")
        return "|".join(parts)

    @staticmethod
    def _payload_id(payload: dict[str, Any]) -> str:
        normalized = {
            "schema": int(payload.get("schema") or 0),
            "client": payload.get("client") if isinstance(payload.get("client"), dict) else {},
            "session": payload.get("session") if isinstance(payload.get("session"), dict) else {},
            "always": payload.get("always") if isinstance(payload.get("always"), list) else [],
            "opt_in": payload.get("opt_in") if isinstance(payload.get("opt_in"), list) else [],
        }
        raw = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    def _client_payload(self) -> dict[str, Any]:
        return {
            "app_version": APP_VERSION,
            "os_family": self._os_key(),
            "os_version": self._clean_value(platform.release()),
            "arch": self._clean_value(platform.machine()),
            "locale": self._clean_value(self._local_config().get("language", "en")),
            "timezone": self._timezone_bucket(),
            "python": self._clean_value(f"{sys.version_info.major}.{sys.version_info.minor}"),
        }

    def _timezone_bucket(self) -> str:
        offset_seconds = -time.timezone
        if time.daylight and time.localtime().tm_isdst:
            offset_seconds = -time.altzone
        abs_offset = abs(int(offset_seconds))
        offset_hours, remaining_seconds = divmod(abs_offset, 3600)
        offset_minutes = remaining_seconds // 60
        if offset_hours == 0 and offset_minutes == 0:
            return "utc"
        sign = "plus" if offset_seconds > 0 else "minus"
        if offset_minutes:
            return f"utc_{sign}_{offset_hours}_{offset_minutes}"
        return f"utc_{sign}_{offset_hours}"

    def _counter_events(self, counters: dict[str, int]) -> list[dict[str, Any]]:
        now = int(time.time())
        events = []
        for key, value in sorted(counters.items()):
            event, dims = self._parse_counter_key(key)
            if not event:
                continue
            events.append(
                {
                    "name": event,
                    "ts": now,
                    "dims": dims,
                    "value": int(value),
                }
            )
        return events

    def _parse_counter_key(self, key: str) -> tuple[str, dict[str, str]]:
        parts = [part for part in str(key or "").split("|") if part]
        if not parts:
            return "", {}
        event = parts[0]
        dims: dict[str, str] = {}
        for part in parts[1:]:
            name, _, value = part.partition("=")
            if name and value:
                dims[name] = value
        return event, dims

    def _clean_value(self, value: Any) -> str:
        text = str(value or "").strip().lower().replace(" ", "_").replace(".", "_")
        filtered = "".join(ch for ch in text if ch.isalnum() or ch in "_-")
        return filtered[: self._MAX_DIM_LEN]

    def _bucket_seconds(self, seconds: float) -> str:
        value = max(0, int(seconds or 0))
        if value < 3:
            return "lt3s"
        if value < 10:
            return "3_9s"
        if value < 30:
            return "10_29s"
        if value < 60:
            return "30_59s"
        if value < 180:
            return "1_2m"
        if value < 600:
            return "3_9m"
        if value < 1800:
            return "10_29m"
        return "30m_plus"

    def _bucket_bytes(self, bytes_count: int) -> str:
        size = max(0, int(bytes_count or 0))
        if size <= 0:
            return "unknown"
        if size < 1_000_000:
            return "lt1mb"
        if size < 10_000_000:
            return "1_9mb"
        if size < 50_000_000:
            return "10_49mb"
        if size < 200_000_000:
            return "50_199mb"
        return "200mb_plus"

    def _bucket_count(self, count: int) -> str:
        value = max(0, int(count or 0))
        if value <= 0:
            return "0"
        if value == 1:
            return "1"
        if value < 4:
            return "2_3"
        if value < 8:
            return "4_7"
        if value < 16:
            return "8_15"
        return "16_plus"

    def _os_key(self) -> str:
        return {
            "Windows": "windows",
            "Linux": "linux",
            "Darwin": "macos",
        }.get(platform.system(), "other")

    def _launch_dims(
        self,
        *,
        mode: str,
        with_mods: bool,
        game: str,
        mod_count: int,
        via_steam: bool,
    ) -> dict[str, str]:
        return {
            "game": self._clean_value(game) or "unknown",
            "mode": self._clean_value(mode) or "unknown",
            "mods": "yes" if with_mods else "no",
            "mod_count": self._bucket_count(mod_count),
            "os": self._os_key(),
            "launch": "steam" if via_steam else "direct",
        }

    def _tab_name(self, index: int) -> str:
        if not self._window or not hasattr(self._window, "main_tab_widget"):
            return "unknown"
        widget = self._window.main_tab_widget.widget(index)
        if widget is getattr(self._window, "mods_browser_tab", None):
            return "mods_browser"
        if widget is getattr(self._window, "library_tab", None):
            return "library"
        return "unknown"

    def _on_tab_changed(self, index: int) -> None:
        name = self._tab_name(index)
        if name != "unknown":
            self.count("tab_opened", tab=name)
            self.count("tab_opened_detail", scope="opt_in", tab=name)

    def _on_search_text_changed(self, area: str, text: str) -> None:
        active = bool(str(text or "").strip())
        if active and not self._active_searches.get(area, False):
            length_bucket = self._query_length_bucket(text)
            self.count("search_started", area=area, length=length_bucket)
            self.count(
                "search_started_detail",
                scope="opt_in",
                area=area,
                length=length_bucket,
            )
        self._active_searches[area] = active

    def _query_length_bucket(self, text: str) -> str:
        length = len(str(text or "").strip())
        if length < 4:
            return "2_3"
        if length < 9:
            return "4_8"
        if length < 17:
            return "9_16"
        return "17_plus"

    def _mods_browser_query_length_bucket(self, text: str) -> str:
        length = len(str(text or "").strip())
        if length <= 0:
            return "0"
        if length == 1:
            return "1"
        if length < 5:
            return "2_4"
        if length < 13:
            return "5_12"
        return "13_plus"

    def _mod_common_dims(self, mod) -> dict[str, str]:
        data = self._mod_detail_dims(mod, include_name=False)
        return {
            key: value
            for key, value in data.items()
            if key
            in {
                "game",
                "source",
                "category",
                "item_type",
                "ref",
                "local_ref",
                "mod_version",
                "game_version",
            }
        }

    def _mod_detail_dims(self, mod, *, include_name: bool) -> dict[str, str]:
        if mod is None:
            return {}
        raw_mod_id = get_mod_id(mod)
        mod_id = self._clean_value(raw_mod_id)
        gb_type, gb_id = parse_gamebanana_mod_id(mod_id)
        game = self._clean_value(
            mod.get("game") if isinstance(mod, dict) else getattr(mod, "game", "")
        )
        version = self._clean_value(
            mod.get("version") if isinstance(mod, dict) else getattr(mod, "version", "")
        )
        game_version = self._clean_value(
            mod.get("game_version")
            if isinstance(mod, dict)
            else getattr(mod, "game_version", "")
        )
        category = self._clean_value(
            (
                mod.get("gamebanana_category")
                if isinstance(mod, dict)
                else getattr(mod, "gamebanana_category", None)
            )
            or (
                mod.get("category")
                if isinstance(mod, dict)
                else getattr(mod, "category", None)
            )
        )
        dims = {
            "game": game or "unknown",
            "source": "gamebanana" if gb_id else "local",
        }
        if category:
            dims["category"] = category
        if version:
            dims["mod_version"] = version
        if game_version:
            dims["game_version"] = game_version
        if gb_type and gb_id:
            dims["item_type"] = gb_type
            dims["ref"] = f"gb_{gb_type}_{gb_id}"
            if include_name:
                name = self._clean_value(get_mod_name(mod))
                if name and name != "unknown":
                    dims["name"] = name
        else:
            local_ref = self._local_mod_ref(raw_mod_id, get_mod_name(mod))
            if local_ref:
                dims["local_ref"] = local_ref
                if include_name:
                    name = self._clean_value(get_mod_name(mod))
                    if name and name != "unknown":
                        dims["name"] = name
        return dims

    def _record_mod_detail(
        self, event: str, field_name: str, field_value: str, mod
    ) -> None:
        dims = self._mod_detail_dims(mod, include_name=True)
        if "ref" not in dims and "local_ref" not in dims:
            return
        payload = {**dims}
        payload[self._clean_value(field_name)] = self._clean_value(field_value)
        self.count(event, scope="opt_in", **payload)

    def _normalized_mod_refs(
        self, mod_refs: list[dict[str, str]] | None
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in mod_refs or []:
            if not isinstance(item, dict):
                continue
            ref = self._clean_value(item.get("ref"))
            if not ref or ref in seen:
                continue
            seen.add(ref)
            payload = {"ref": ref}
            name = self._clean_value(item.get("name"))
            if name:
                payload["name"] = name
            item_type = self._clean_value(item.get("item_type"))
            if item_type:
                payload["item_type"] = item_type
            source = self._clean_value(item.get("source"))
            if source:
                payload["source"] = source
            result.append(payload)
        return result

    def _local_mod_ref(self, mod_id: Any, mod_name: Any = "") -> str:
        seed = f"{mod_id or ''}|{mod_name or ''}".strip("|")
        if not seed:
            return ""
        digest = hashlib.sha256(str(seed).encode("utf-8", errors="ignore")).hexdigest()
        return f"local_{digest[:12]}"

    def _plugin_payload_dims(
        self,
        plugin,
        *,
        source: str = "",
    ) -> dict[str, str]:
        if isinstance(plugin, dict):
            plugin_id = plugin.get("id") or plugin.get("plugin_id")
            plugin_name = plugin.get("name")
            version = plugin.get("version")
            plugin_source = plugin.get("source", source)
        else:
            plugin_id = getattr(plugin, "id", None) or getattr(
                plugin, "plugin_id", None
            )
            plugin_name = getattr(plugin, "name", None)
            version = getattr(plugin, "version", None)
            plugin_source = source
        dims = {
            "plugin_id": self._clean_value(plugin_id),
            "plugin_name": self._clean_value(plugin_name),
            "plugin_version": self._clean_value(version),
            "source": self._clean_value(plugin_source) or "installed",
        }
        return {key: value for key, value in dims.items() if value}

    def _record_plugin_detail(self, event: str, plugin, *, source: str) -> None:
        dims = self._plugin_payload_dims(plugin, source=source)
        if not dims.get("plugin_id"):
            return
        self.count(event, scope="opt_in", **dims)

    def _download_common_dims(self, record) -> dict[str, str]:
        metadata = getattr(record, "metadata", None) or {}
        dims = {
            "source": self._clean_value(getattr(record, "source_kind", "unknown"))
            or "unknown",
            "target": self._clean_value(getattr(record, "target_kind", "unknown"))
            or "unknown",
            "auto": "yes" if bool(getattr(record, "auto_use", False)) else "no",
            "cleanup": "yes"
            if bool(getattr(record, "delete_after_use", False))
            else "no",
        }
        game = self._clean_value(metadata.get("game"))
        if game:
            dims["game"] = game
        if metadata.get("gb_mod_id"):
            item_type = self._clean_value(metadata.get("item_type") or "mod") or "mod"
            mod_id = self._clean_value(metadata.get("gb_mod_id"))
            if mod_id:
                dims["ref"] = f"gb_{item_type}_{mod_id}"
                dims["item_type"] = item_type
            category = self._clean_value(metadata.get("category"))
            if category:
                dims["category"] = category
            compatibility = self._clean_value(metadata.get("compatibility"))
            if compatibility:
                dims["compat"] = compatibility
        elif metadata.get("plugin_id"):
            plugin_id = self._clean_value(metadata.get("plugin_id"))
            if plugin_id:
                dims["plugin_id"] = plugin_id
        else:
            local_ref = self._local_mod_ref(metadata.get("id"), metadata.get("name"))
            if local_ref and str(getattr(record, "target_kind", "")).lower() == "mod":
                dims["local_ref"] = local_ref
        return dims

    def _download_detail_dims(self, record) -> dict[str, str]:
        metadata = getattr(record, "metadata", None) or {}
        dims = self._download_common_dims(record)
        if metadata.get("gb_mod_id"):
            item_type = self._clean_value(metadata.get("item_type") or "mod") or "mod"
            mod_id = self._clean_value(metadata.get("gb_mod_id"))
            if mod_id:
                dims["ref"] = f"gb_{item_type}_{mod_id}"
                dims["item_type"] = item_type
                name = self._clean_value(metadata.get("name"))
                if name:
                    dims["name"] = name
            file_id = self._clean_value(metadata.get("gb_file_id"))
            if file_id:
                dims["file_id"] = file_id
            file_name = self._clean_value(metadata.get("file_name"))
            if file_name:
                dims["file"] = file_name
            compatibility = self._clean_value(metadata.get("compatibility"))
            if compatibility:
                dims["compat"] = compatibility
            category = self._clean_value(metadata.get("category"))
            if category:
                dims["category"] = category
            version = self._clean_value(metadata.get("version"))
            if version:
                dims["mod_version"] = version
        elif metadata.get("plugin_id"):
            dims.update(
                self._plugin_payload_dims(
                    metadata,
                    source=metadata.get("source", "catalog"),
                )
            )
        else:
            ext = self._file_extension(
                metadata.get("file_name")
                or getattr(record, "file_path", "")
                or getattr(record, "source_file_path", "")
                or getattr(record, "source_url", "")
            )
            if ext:
                dims["ext"] = self._clean_value(ext)
        size_bucket = self._bucket_bytes(
            getattr(record, "bytes_total", 0)
            or getattr(record, "bytes_received", 0)
        )
        if size_bucket != "unknown":
            dims["size"] = size_bucket
        return dims

    def _file_extension(self, value: Any) -> str:
        filename = str(value or "").split("?", 1)[0].split("#", 1)[0]
        _, ext = os.path.splitext(filename)
        return ext.lstrip(".").lower()[:10]

    def _on_download_record_added(self, record) -> None:
        self.count("download_enqueued", **self._download_common_dims(record))
        detail_dims = self._download_detail_dims(record)
        if detail_dims:
            self.count("download_enqueued_detail", scope="opt_in", **detail_dims)

    def _on_download_record_updated(self, record) -> None:
        state = (
            self._clean_value(getattr(record, "download_status", "")),
            self._clean_value(getattr(record, "use_status", "")),
            bool(getattr(record, "ever_installed", False)),
        )
        record_id = getattr(record, "id", "")
        if not record_id or self._download_states.get(record_id) == state:
            return
        self._download_states[record_id] = state
        common_dims = self._download_common_dims(record)
        detail_dims = self._download_detail_dims(record)
        download_state, use_state, was_installed = state
        match (download_state, use_state, was_installed):
            case ("downloading", _, _):
                self.count("download_started", **common_dims)
                if detail_dims:
                    self.count(
                        "download_started_detail",
                        scope="opt_in",
                        **detail_dims,
                    )
            case ("downloaded", "pending_auto_use", _):
                self.count("download_completed", **common_dims)
                if detail_dims:
                    self.count(
                        "download_completed_detail",
                        scope="opt_in",
                        **detail_dims,
                    )
            case ("downloaded", "ready_to_use", False):
                self.count("download_completed", **common_dims)
                self.count("download_ready", **common_dims)
                if detail_dims:
                    self.count(
                        "download_completed_detail",
                        scope="opt_in",
                        **detail_dims,
                    )
            case ("failed", _, _):
                self.count("download_failed", **common_dims)
                if detail_dims:
                    self.count("download_failed_detail", scope="opt_in", **detail_dims)
            case ("cancelled", _, _):
                self.count("download_cancelled", **common_dims)
                if detail_dims:
                    self.count(
                        "download_cancelled_detail",
                        scope="opt_in",
                        **detail_dims,
                    )
            case (_, "using", _):
                self.count("use_started", **common_dims)
                if detail_dims:
                    self.count("use_started_detail", scope="opt_in", **detail_dims)
            case (_, "needs_manual_install", _):
                self.count("use_manual_needed", **common_dims)
                if detail_dims:
                    self.count(
                        "use_manual_needed_detail",
                        scope="opt_in",
                        **detail_dims,
                    )
            case (_, "failed", _):
                self.count("use_failed", **common_dims)
                if detail_dims:
                    self.count("use_failed_detail", scope="opt_in", **detail_dims)
            case (_, "ready_to_use", True):
                self.count("use_completed", **common_dims)
                if detail_dims:
                    self.count("use_completed_detail", scope="opt_in", **detail_dims)
