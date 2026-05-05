from utils.process_utils import build_external_process_env


def test_build_external_process_env_restores_ld_library_path_from_orig():
    env = {
        "LD_LIBRARY_PATH": "/bundle/lib",
        "LD_LIBRARY_PATH_ORIG": "/usr/lib:/usr/local/lib",
        "PATH": "/usr/bin",
    }

    result = build_external_process_env(system="Linux", base_env=env)

    assert result is not None
    assert result["LD_LIBRARY_PATH"] == "/usr/lib:/usr/local/lib"
    assert result["LD_LIBRARY_PATH_ORIG"] == "/usr/lib:/usr/local/lib"
    assert result["PATH"] == "/usr/bin"


def test_build_external_process_env_removes_ld_library_path_when_orig_missing():
    env = {
        "LD_LIBRARY_PATH": "/bundle/lib",
        "PATH": "/usr/bin",
    }

    result = build_external_process_env(system="Linux", base_env=env)

    assert result is not None
    assert "LD_LIBRARY_PATH" not in result
    assert result["PATH"] == "/usr/bin"


def test_build_external_process_env_returns_none_outside_linux():
    env = {"LD_LIBRARY_PATH": "/bundle/lib"}

    result = build_external_process_env(system="Windows", base_env=env)

    assert result is None
