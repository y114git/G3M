from types import SimpleNamespace

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QPushButton, QTabWidget, QWidget


def _host():
    host = QWidget()
    host.resize(1000, 700)
    host.app_state = SimpleNamespace(
        is_settings_view=False,
        local_config={},
    )
    host.main_tab_widget = QTabWidget(host)
    host.main_tab_widget.setGeometry(0, 60, 1000, 580)
    host.mods_browser_tab = QWidget()
    host.library_tab = QWidget()
    host.main_tab_widget.addTab(host.mods_browser_tab, "Browser")
    host.main_tab_widget.addTab(host.library_tab, "Library")
    host.settings_tab_widget = QTabWidget(host)
    host.settings_tab_widget.setGeometry(0, 60, 1000, 580)
    for name in ("App", "Appearance", "Game", "Browser", "Library", "Plugins"):
        host.settings_tab_widget.addTab(QWidget(), name)
    host.settings_tab_widget.hide()

    def toggle_settings():
        host.app_state.is_settings_view = not host.app_state.is_settings_view
        host.main_tab_widget.setVisible(not host.app_state.is_settings_view)
        host.settings_tab_widget.setVisible(host.app_state.is_settings_view)

    host.settings_ui = SimpleNamespace(toggle_settings_view=toggle_settings)
    for name in (
        "settings_button",
        "settings_game_path_edit",
        "modgame_combo",
        "downloads_button",
        "add_mod_button",
        "profile_combo",
        "library_game_versions_button",
        "priority_button",
        "create_modpack_button",
        "diagnostics_button",
        "library_modding_tools_button",
        "shortcut_button",
        "community_button",
        "action_button",
    ):
        setattr(host, name, QPushButton(name, host))
    host.show()
    return host


def test_tour_navigates_to_settings_and_restores_view(qapp):
    from ui.onboarding_tour import OnboardingTour

    host = _host()
    tour = OnboardingTour(host)
    tour._show_step(2)
    qapp.processEvents()

    assert host.app_state.is_settings_view is True
    assert host.settings_tab_widget.currentIndex() == 0

    tour._complete(False)

    assert host.app_state.is_settings_view is False
    assert tour.isHidden()


def test_tour_started_in_settings_restores_main_and_settings_tabs(qapp):
    from ui.onboarding_tour import _STEPS, OnboardingTour

    host = _host()
    host.main_tab_widget.setCurrentWidget(host.library_tab)
    host.settings_ui.toggle_settings_view()
    host.settings_tab_widget.setCurrentIndex(4)
    tour = OnboardingTour(host)
    browser_step = next(i for i, step in enumerate(_STEPS) if step.key == "browser")

    tour._show_step(browser_step)
    qapp.processEvents()
    tour._complete(False)

    assert host.app_state.is_settings_view is True
    assert host.main_tab_widget.currentWidget() is host.library_tab
    assert host.settings_tab_widget.currentIndex() == 4


def test_tour_temporarily_shows_hidden_browser_and_restores_it(qapp):
    from ui.onboarding_tour import _STEPS, OnboardingTour

    host = _host()
    host.main_tab_widget.removeTab(host.main_tab_widget.indexOf(host.mods_browser_tab))
    tour = OnboardingTour(host)
    browser_step = next(i for i, step in enumerate(_STEPS) if step.key == "browser")

    tour._show_step(browser_step)
    qapp.processEvents()

    assert host.main_tab_widget.currentWidget() is host.mods_browser_tab

    tour._complete(False)

    assert host.main_tab_widget.indexOf(host.mods_browser_tab) == -1


def test_tour_highlights_game_versions_button(qapp):
    from ui.onboarding_tour import _STEPS, OnboardingTour

    host = _host()
    tour = OnboardingTour(host)
    step = next(i for i, item in enumerate(_STEPS) if item.key == "game_versions")

    tour._show_step(step)
    qapp.processEvents()

    assert host.main_tab_widget.currentWidget() is host.library_tab
    assert not tour._target_rect.isEmpty()


def test_tour_skip_marks_completion(qapp):
    from ui.onboarding_tour import OnboardingTour

    host = _host()
    tour = OnboardingTour(host)
    completed = []
    tour.completed.connect(completed.append)

    tour.skip_button.click()

    assert completed == [False]


def test_completed_tour_is_deleted(qapp):
    from ui.onboarding_tour import OnboardingTour

    host = _host()
    tour = OnboardingTour(host)

    tour._complete(False)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    assert sip.isdeleted(tour)


def test_tour_resize_tracks_host(qapp):
    from ui.onboarding_tour import OnboardingTour

    host = _host()
    tour = OnboardingTour(host)

    host.resize(820, 620)
    qapp.processEvents()

    assert tour.size() == host.size()


def test_tour_finish_can_request_settings(qapp):
    from ui.onboarding_tour import OnboardingTour

    host = _host()
    tour = OnboardingTour(host)
    completed = []
    tour.completed.connect(completed.append)

    tour._complete(True)

    assert completed == [True]
