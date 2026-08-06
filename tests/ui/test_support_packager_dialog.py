from PyQt6.QtCore import qInstallMessageHandler
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QCheckBox

from services.localization_service import localization_service
from services.support_package_service import SupportPackageService
from ui.dialogs.support_packager_dialog import SupportPackagerDialog


def test_support_packager_toggle_does_not_change_native_geometry(
    qapp, app_state, tmp_path
):
    service = SupportPackageService(app_state, str(tmp_path))
    dialog = SupportPackagerDialog(app_state, service=service)
    messages = []
    previous_handler = qInstallMessageHandler(
        lambda _kind, _context, message: messages.append(message)
    )
    try:
        dialog.show()
        qapp.processEvents()
        dialog._custom.setChecked(True)
        QTest.qWait(30)
        dialog._custom.setChecked(False)
        QTest.qWait(30)
    finally:
        qInstallMessageHandler(previous_handler)
        dialog.close()

    assert not any("QWindowsWindow::setGeometry" in message for message in messages)


def test_support_packager_uses_localized_collapsible_standard_checkboxes(
    qapp, app_state, tmp_path
):
    service = SupportPackageService(app_state, str(tmp_path))
    dialog = SupportPackagerDialog(app_state, service=service)
    original_language = localization_service.get_current_language()
    try:
        assert dialog._custom.isChecked() is False
        assert dialog._items
        assert all(isinstance(item, QCheckBox) for item in dialog._items.values())
        assert all(item.isChecked() for item in dialog._items.values())
        assert all(not item.isEnabled() for item in dialog._items.values())
        assert not dialog._sections_scroll.isHidden()
        assert all(
            not content.isHidden() for content in dialog._section_contents.values()
        )
        assert dialog._range.isEnabled() is True
        assert all(
            not label.text().startswith("[")
            for label, _key, _is_key in dialog._section_titles.values()
        )
        assert dialog._section_titles["configuration"][0].text() != ""
        option_texts = [item.text() for item in dialog._items.values()]
        assert len(option_texts) == len(set(option_texts))

        dialog._custom.setChecked(True)
        qapp.processEvents()

        assert not dialog._sections_scroll.isHidden()
        assert all(item.isEnabled() for item in dialog._items.values())
        assert all(
            not content.isHidden() for content in dialog._section_contents.values()
        )
        arrow = dialog._section_arrows["system"]
        dialog._toggle_section("system")
        assert arrow.text() == "▶"
        dialog._items["app.version"].setChecked(False)
        dialog._custom.setChecked(False)
        assert not dialog._sections_scroll.isHidden()
        assert all(
            not content.isHidden() for content in dialog._section_contents.values()
        )
        assert dialog._items["app.version"].isChecked() is True
        assert dialog._items["app.version"].isEnabled() is False
        assert dialog._range.isEnabled() is True
        for language in ("en", "es", "ja", "ko", "ru", "zh_cn", "zh_tw"):
            assert localization_service.load_language(language)
            dialog.relocalize_ui()
            assert all(
                not label.text().startswith("[")
                for label, _key, _is_key in dialog._section_titles.values()
            )
    finally:
        localization_service.load_language(original_language)
        dialog.close()
