"""Lightweight aggregated analytics service."""

from __future__ import annotations

import base64
import contextlib
import gzip
import json
import logging
import os
import platform
import sys
import time
from collections import Counter
from typing import Any

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from config.config import APP_VERSION, CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_SHORT
from utils.file_utils import load_json, save_json
from utils.network_utils import cloud_function_request

logger = logging.getLogger(__name__)


class _AnalyticsUploadWorker(QObject):
    finished = pyqtSignal(bool, int)

    def __init__(self, batch: list[dict[str, Any]]) -> None:
        super().__init__()
        self._batch = batch

    def run(self) -> None:
        try:
            encoded = base64.b64encode(
                gzip.compress(
                    json.dumps({"v": 1, "b": self._batch}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                    compresslevel=9,
                )
            ).decode("ascii")
            response = cloud_function_request(
                "post",
                f"{CLOUD_FUNCTIONS_BASE_URL}/ingestAnalytics",
                json={"encoding": "gzip+base64", "payload": encoded},
                timeout=NETWORK_TIMEOUT_SHORT,
            )
            self.finished.emit(bool(response) and getattr(response, "status_code", 500) < 300, len(self._batch))
        except Exception as e:
            logger.debug("Analytics flush failed: %s", e, exc_info=True)
            self.finished.emit(False, len(self._batch))


class AnalyticsService(QObject):
    """Aggregates cheap anonymous analytics and flushes compressed batches."""

    _MAX_DIM_LEN = 40

    def __init__(self, app_state, base_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self._dir = os.path.join(base_dir, "analytics")
        self._state_path = os.path.join(self._dir, "telemetry_state.json")
        self._always_on = Counter()
        self._opt_in = Counter()
        self._pending: list[dict[str, Any]] = []
        self._download_states: dict[str, tuple[str, str]] = {}
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
        self._load_state()
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_async)
        self.count("app_launch", os=self._os_key())
        self.count(
            "app_launch_detail",
            scope="opt_in",
            os=self._os_key(),
            locale=self._clean_value(self.app_state.local_config.get("language", "en")),
            py=self._clean_value(f"{sys.version_info.major}.{sys.version_info.minor}"),
        )

    @property
    def opt_in_enabled(self) -> bool:
        return bool(self.app_state.local_config.get("analytics_opt_in_enabled", False))

    def set_opt_in_enabled(self, enabled: bool) -> None:
        previous = self.opt_in_enabled
        self.app_state.local_config["analytics_opt_in_enabled"] = bool(enabled)
        if enabled and not previous:
            self.count("opt_in_enabled")
        if not enabled:
            self._opt_in.clear()
            if self._upload_in_flight:
                self._upload_in_flight = [
                    {**payload, "oi": {}}
                    for payload in self._upload_in_flight
                    if isinstance(payload, dict) and (payload.get("ao") or payload.get("oi"))
                ]
            retained = []
            for payload in self._pending:
                if not isinstance(payload, dict):
                    continue
                stripped = {**payload, "oi": {}}
                if payload.get("ao") or payload.get("oi"):
                    retained.append(stripped)
            self._pending = retained
            self._save_state()

    def attach_window(self, window) -> None:
        if self._window is window:
            return
        self._window = window
        if hasattr(window, "main_tab_widget"):
            window.main_tab_widget.currentChanged.connect(self._on_tab_changed)
            QTimer.singleShot(0, lambda: self._on_tab_changed(window.main_tab_widget.currentIndex()))
        self.app_state.search_text_changed.connect(
            lambda text: self._on_search_text_changed("mods_browser", text)
        )
        self.app_state.library_search_text_changed.connect(
            lambda text: self._on_search_text_changed("library", text)
        )
        if hasattr(window, "downloads_manager"):
            window.downloads_manager.record_added.connect(self._on_download_record_added)
            window.downloads_manager.record_updated.connect(self._on_download_record_updated)
        app = getattr(window, "instance", None)
        with contextlib.suppress(Exception):
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
        if app:
            with contextlib.suppress(Exception):
                app.aboutToQuit.connect(self.shutdown)
        QTimer.singleShot(2500, self.flush)

    def mark_ui_ready(self) -> None:
        if self._ui_ready_recorded:
            return
        self._ui_ready_recorded = True
        self.count("app_ready", startup=self._bucket_seconds(time.monotonic() - self._startup_started_at))

    def record_dialog_opened(self, name: str) -> None:
        self.count("dialog_opened", name=name)

    def record_setting_changed(self, name: str, enabled: bool) -> None:
        self.count("setting_changed", name=name, state="on" if enabled else "off")

    def record_search_results(self, area: str, count: int) -> None:
        bucket = (
            "0"
            if count <= 0
            else "1" if count == 1 else "2_9" if count < 10 else "10_49" if count < 50 else "50_plus"
        )
        self.count("search_results", area=area, count=bucket)

    def record_mod_opened(self, area: str) -> None:
        self.count("mod_opened", area=area)

    def record_mod_details_opened(self, area: str) -> None:
        self.count("mod_details_opened", area=area)

    def record_launch_started(self, *, mode: str, with_mods: bool) -> None:
        self.count("game_launch_started", mode=mode, mods="yes" if with_mods else "no")

    def record_launch_finished(self, seconds: float, *, mode: str, with_mods: bool) -> None:
        self.record_timing(
            "game_launch_finished",
            seconds,
            mode=mode,
            mods="yes" if with_mods else "no",
        )

    def record_launch_failed(self, *, reason: str, mode: str, with_mods: bool) -> None:
        self.count(
            "game_launch_failed",
            reason=reason,
            mode=mode,
            mods="yes" if with_mods else "no",
        )

    def record_update_check(self, outcome: str) -> None:
        self.count("update_check", outcome=outcome)

    def count(self, event: str, scope: str = "always", value: int = 1, **dims) -> None:
        if value <= 0:
            return
        if scope == "opt_in" and not self.opt_in_enabled:
            return
        counter = self._opt_in if scope == "opt_in" else self._always_on
        key = self._event_key(event, dims)
        counter[key] += int(value)
        if (scope == "always" and sum(self._always_on.values()) % 24 == 0) or (
            scope == "opt_in" and sum(self._opt_in.values()) % 20 == 0
        ):
            self._schedule_flush(1500)

    def record_timing(self, event: str, seconds: float, scope: str = "always", **dims) -> None:
        dims = dict(dims)
        dims["bucket"] = self._bucket_seconds(seconds)
        self.count(event, scope=scope, **dims)

    def shutdown(self) -> None:
        if self._session_closed:
            return
        self._session_closed = True
        duration = time.monotonic() - self._session_started_at
        self.count("session_end", duration=self._bucket_seconds(duration))
        self.count(
            "session_end_detail",
            scope="opt_in",
            duration=self._bucket_seconds(duration),
            locale=self._clean_value(self.app_state.local_config.get("language", "en")),
            scale=self._clean_value(int(float(self.app_state.local_config.get("ui_scale", 1.0)) * 100)),
            theme=self._clean_value("custom" if any(self.app_state.local_config.get(k) for k in (
                "custom_background_color",
                "custom_elements_color",
                "custom_border_color",
                "custom_hover_color",
                "custom_select_color",
                "custom_main_text_color",
                "custom_secondary_text_color",
            )) else "default"),
        )
        self._enqueue_session_payload()
        self._flush_async(force=True)

    def flush(self, force: bool = False) -> bool:
        self._flush_async(force=force)
        return not self._pending and self._upload_thread is None

    def _flush_async(self, force: bool = False) -> None:
        if not force:
            self._flush_timer.stop()
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
        worker.finished.connect(self._on_upload_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._upload_in_flight = list(batch)
        self._upload_batch_size = len(batch)
        self._upload_thread = thread
        self._upload_worker = worker
        self._save_state()
        thread.start()

    def _on_upload_finished(self, success: bool, batch_size: int) -> None:
        in_flight = list(self._upload_in_flight)
        if success and in_flight:
            remaining_pending = list(self._pending)
            for payload in in_flight:
                with contextlib.suppress(ValueError):
                    remaining_pending.remove(payload)
            self._pending = remaining_pending
        self._upload_worker = None
        self._upload_thread = None
        self._upload_batch_size = 0
        self._upload_in_flight = []
        self._save_state()
        if self._pending and not self._session_closed:
            self._schedule_flush(250)

    def _schedule_flush(self, delay_ms: int = 3000) -> None:
        if self._session_closed:
            return
        self._flush_timer.start(max(250, int(delay_ms)))

    def _enqueue_session_payload(self, transient: bool = False) -> None:
        if not self._always_on and not self._opt_in:
            return
        payload = {
            "a": APP_VERSION,
            "d": time.strftime("%Y-%m-%d", time.gmtime()),
            "ao": dict(self._always_on),
            "oi": dict(self._opt_in),
        }
        self._always_on.clear()
        self._opt_in.clear()
        self._pending.append(payload)
        if not transient:
            self._save_state()

    def _load_state(self) -> None:
        os.makedirs(self._dir, exist_ok=True)
        data = load_json(self._state_path) or {}
        pending = data.get("pending")
        if isinstance(pending, list):
            self._pending = [item for item in pending if isinstance(item, dict)][-20:]

    def _save_state(self) -> None:
        os.makedirs(self._dir, exist_ok=True)
        save_json(self._state_path, {"pending": self._pending[-20:]}, indent=2)

    def _event_key(self, event: str, dims: dict[str, Any]) -> str:
        parts = [self._clean_value(event)]
        for key, value in sorted(dims.items()):
            clean = self._clean_value(value)
            if clean:
                parts.append(f"{self._clean_value(key)}={clean}")
        return "|".join(parts)

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

    def _os_key(self) -> str:
        return {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(
            platform.system(), "other"
        )

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

    def _on_search_text_changed(self, area: str, text: str) -> None:
        active = bool(str(text or "").strip())
        if active and not self._active_searches.get(area, False):
            self.count("search_started", area=area, length=self._query_length_bucket(text))
            self.count(
                "search_started_detail",
                scope="opt_in",
                area=area,
                length=self._query_length_bucket(text),
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

    def _on_download_record_added(self, record) -> None:
        self.count(
            "download_enqueued",
            source=self._clean_value(getattr(record, "source_kind", "unknown")),
            target=self._clean_value(getattr(record, "target_kind", "unknown")),
        )

    def _on_download_record_updated(self, record) -> None:
        state = (
            self._clean_value(getattr(record, "download_status", "")),
            self._clean_value(getattr(record, "use_status", "")),
        )
        record_id = getattr(record, "id", "")
        if not record_id or self._download_states.get(record_id) == state:
            return
        self._download_states[record_id] = state
        dims = {
            "source": self._clean_value(getattr(record, "source_kind", "unknown")),
            "target": self._clean_value(getattr(record, "target_kind", "unknown")),
        }
        match state:
            case ("downloading", _):
                self.count("download_started", **dims)
            case ("downloaded", _):
                self.count("download_completed", **dims)
            case ("failed", _):
                self.count("download_failed", **dims)
            case ("cancelled", _):
                self.count("download_cancelled", **dims)
            case (_, "using"):
                self.count("use_started", **dims)
            case (_, "needs_manual"):
                self.count("use_manual_needed", **dims)
            case (_, "failed"):
                self.count("use_failed", **dims)
