"""Presents Pizza Oven conversion workflows."""

from __future__ import annotations

import logging
import os
import shutil

from PyQt6.QtWidgets import QDialog, QMessageBox

from services.game_detection_service import is_valid_game_path
from services.localization_service import tr
from workers.install.pizza_oven_conversion_worker import PizzaOvenConversionWorker

logger = logging.getLogger(__name__)


class PizzaOvenConversionPresenter:
    """UI orchestration for PizzaOven conversion from manual-install fallbacks."""

    def __init__(
        self,
        app_state,
        feedback_service,
        settings_service,
        mod_service,
        conversion_service,
        parent=None,
    ) -> None:
        self.app_state = app_state
        self.feedback_service = feedback_service
        self.settings_service = settings_service
        self.mod_service = mod_service
        self.conversion_service = conversion_service
        self.parent = parent
        self._active_workers: set[PizzaOvenConversionWorker] = set()

    def should_offer_conversion(
        self, prepared_path: str, gamebanana_metadata: dict | None = None
    ) -> bool:
        try:
            if gamebanana_metadata:
                raw_game = gamebanana_metadata.get("game")
                if raw_game:
                    game_value = str(raw_game).strip().lower()
                    if game_value != "pizzatower":
                        return False
            return self.conversion_service.inspect_source(prepared_path).eligible
        except Exception as e:
            logger.debug("PO inspection failed for %s: %s", prepared_path, e, exc_info=True)
            return False

    def prompt_with_manual_options(
        self,
        parent,
        *,
        error_title: str,
        error_text: str,
        informative_text: str,
        prepared_path: str,
        source_file_path: str | None,
        temp_dir: str | None,
        initial_game_type: str | None = None,
        gamebanana_metadata: dict | None = None,
        on_success=None,
    ) -> bool:
        resolved_game_type = initial_game_type or self._current_game_type()
        while True:
            msg_box = QMessageBox(parent)
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle(error_title)
            msg_box.setText(error_text)
            msg_box.setInformativeText(informative_text)
            manual_install_btn = msg_box.addButton(
                tr("ui.manual_install"), QMessageBox.ButtonRole.AcceptRole
            )
            po_convert_btn = None
            if self.should_offer_conversion(prepared_path, gamebanana_metadata):
                po_convert_btn = msg_box.addButton(
                    tr("ui.po_convert"), QMessageBox.ButtonRole.ActionRole
                )
            msg_box.addButton(tr("dialogs.cancel"), QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(manual_install_btn)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == manual_install_btn:
                accepted = self._open_manual_install_dialog(
                    parent,
                    prepared_path=prepared_path,
                    source_file_path=source_file_path,
                    temp_dir=temp_dir,
                    initial_game_type=resolved_game_type,
                    gamebanana_metadata=gamebanana_metadata or {},
                    on_success=on_success,
                )
                if accepted:
                    return True
                continue
            if po_convert_btn is not None and clicked == po_convert_btn:
                if self._run_conversion_flow(
                    parent,
                    prepared_path=prepared_path,
                    source_file_path=source_file_path,
                    temp_dir=temp_dir,
                    gamebanana_metadata=gamebanana_metadata or {},
                    on_success=on_success,
                ):
                    return True
                continue
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    def _open_manual_install_dialog(
        self,
        parent,
        *,
        prepared_path: str,
        source_file_path: str | None,
        temp_dir: str | None,
        initial_game_type: str | None,
        gamebanana_metadata: dict,
        on_success=None,
    ) -> bool:
        from ui.dialogs.manual_install.dialog import ManualModInstallDialog

        dialog = ManualModInstallDialog(
            parent,
            prepared_path,
            gamebanana_metadata=gamebanana_metadata,
            source_file_path=source_file_path,
            initial_game_type=initial_game_type,
        )
        dialog.temp_dir_to_cleanup = None
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        if on_success:
            on_success()
        else:
            self._refresh_mods()
        QMessageBox.information(
            parent,
            tr("dialogs.success"),
            tr("dialogs.mod_created_successfully"),
        )
        return True

    def _run_conversion_flow(
        self,
        parent,
        *,
        prepared_path: str,
        source_file_path: str | None,
        temp_dir: str | None,
        gamebanana_metadata: dict,
        on_success=None,
    ) -> bool:
        from ui.dialogs.pizza_oven_conversion_dialog import PizzaOvenConversionDialog

        dialog = PizzaOvenConversionDialog(parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        game_path = self._ensure_valid_pizzatower_path(parent)
        if not game_path:
            return False
        worker = PizzaOvenConversionWorker(
            self.conversion_service,
            prepared_path,
            self.app_state.mods_dir,
            game_path,
            source_file_path=source_file_path,
            gamebanana_metadata=gamebanana_metadata,
            parent=parent,
        )
        self._active_workers.add(worker)
        self.app_state.is_installing = True
        self.app_state.progress_bar_visible = True
        self.app_state.progress_bar_value = 0
        self.app_state.current_task = worker
        worker.progress.connect(lambda value: setattr(self.app_state, "progress_bar_value", value))
        worker.status.connect(self.feedback_service.update_status)
        worker.conversion_finished.connect(
            lambda success, payload, result, temp=temp_dir, cb=on_success, w=worker: self._on_conversion_finished(
                parent,
                success,
                payload,
                result,
                temp,
                cb,
                w,
            )
        )
        worker.start()
        return True

    def _ensure_valid_pizzatower_path(self, parent) -> str | None:
        from models.game_modes import get_game

        game = get_game("pizzatower")
        if not game:
            return None
        existing = game.get_game_path(self.app_state.local_config)
        if existing and is_valid_game_path(
            existing, skip_data_check=False, game_type="pizzatower"
        ):
            try:
                self.conversion_service.validate_game_path(existing)
                return existing
            except Exception:
                logger.debug(
                    "Stored Pizza Tower path failed PO conversion validation: %s",
                    existing,
                    exc_info=True,
                )
        while True:
            previous_game_mode = self.app_state.game_mode
            self.app_state.game_mode = game
            try:
                prompted = self.settings_service.prompt_for_game_path(is_initial=False)
            finally:
                self.app_state.game_mode = previous_game_mode
            if not prompted:
                return None
            updated = game.get_game_path(self.app_state.local_config)
            if updated and is_valid_game_path(
                updated, skip_data_check=False, game_type="pizzatower"
            ):
                try:
                    self.conversion_service.validate_game_path(updated)
                    return updated
                except Exception:
                    logger.debug(
                        "Prompted Pizza Tower path failed PO conversion validation: %s",
                        updated,
                        exc_info=True,
                    )
            QMessageBox.warning(
                parent,
                tr("errors.error"),
                tr("dialogs.po_convert_invalid_game_path"),
            )

    def _current_game_type(self) -> str | None:
        game_mode = getattr(self.app_state, "game_mode", None)
        return getattr(game_mode, "game_id", None)

    def _on_conversion_finished(
        self,
        parent,
        success: bool,
        payload: str,
        result,
        temp_dir: str | None,
        on_success,
        worker: PizzaOvenConversionWorker,
    ) -> None:
        self.app_state.reset_install_state()
        self._active_workers.discard(worker)
        worker.deleteLater()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        if not success:
            self.feedback_service.show_message(
                "error",
                tr("errors.error"),
                tr("errors.po_convert_failed", error=payload),
            )
            return
        if on_success:
            on_success()
        else:
            self._refresh_mods()
        mod_name = result.mod_dir if hasattr(result, "mod_dir") else payload
        display_name = self._display_mod_name(mod_name)
        success_message = tr("status.po_convert_success", mod_name=display_name)
        self.feedback_service.update_status(success_message, "status_success")
        QMessageBox.information(
            parent,
            tr("dialogs.success"),
            success_message,
        )

    def _refresh_mods(self) -> None:
        self.mod_service.invalidate_mods_cache()
        self.mod_service.load_local_mods()
        self.mod_service.mod_list_updated.emit()

    @staticmethod
    def _display_mod_name(mod_dir: str) -> str:
        return os.path.basename(mod_dir.rstrip("\\/"))
