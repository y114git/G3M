from unittest.mock import Mock, patch

from services.game_detection_service import get_running_game_process_name


def test_running_process_lookup_is_scoped_to_selected_game():
    deltarune = Mock(info={"name": "DELTARUNE.exe"})
    pizza_tower = Mock(info={"name": "PizzaTower.exe"})
    with patch("services.game_detection_service.psutil.process_iter", return_value=[deltarune, pizza_tower]):
        assert get_running_game_process_name(("PizzaTower.exe",)) == "PizzaTower.exe"


def test_running_process_lookup_ignores_unrelated_games():
    process = Mock(info={"name": "DELTARUNE.exe"})
    with patch("services.game_detection_service.psutil.process_iter", return_value=[process]):
        assert get_running_game_process_name(("PizzaTower.exe",)) is None
