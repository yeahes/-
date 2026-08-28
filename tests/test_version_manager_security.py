from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.thread.version_manager_thread import VersionManager
from app.view.main_window import MainWindow


def test_remote_history_update_code_is_never_executed():
    assert not hasattr(VersionManager, "execute_update_code")
    manager = VersionManager.__new__(VersionManager)
    manager.currentVersion = "v1.3.3"
    manager.latestVersion = "v1.3.3"
    manager.history = [
        {
            "version": "v1.3.3",
            "available": True,
            "update_code": "raise RuntimeError('remote code must not execute')",
        }
    ]
    manager.forceUpdate = False
    manager.getLatestVersionInfo = Mock(return_value={"version": "v1.3.3"})
    manager.execute_update_code = Mock()

    assert manager.hasNewVersion() is False
    manager.execute_update_code.assert_not_called()


def test_startup_version_check_respects_setting():
    window = MainWindow.__new__(MainWindow)
    window.versionThread = Mock()

    with patch(
        "app.view.main_window.cfg",
        SimpleNamespace(checkUpdateAtStartUp=SimpleNamespace(value=False)),
    ):
        window._start_version_check_if_enabled()
    window.versionThread.start.assert_not_called()

    with patch(
        "app.view.main_window.cfg",
        SimpleNamespace(checkUpdateAtStartUp=SimpleNamespace(value=True)),
    ):
        window._start_version_check_if_enabled()
    window.versionThread.start.assert_called_once_with()


if __name__ == "__main__":
    test_remote_history_update_code_is_never_executed()
    test_startup_version_check_respects_setting()
    print("version manager security tests passed")
