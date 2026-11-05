"""Render the dashboard with a fake controller; never opens the hardware bridge."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
import tempfile
import app
from test_app_shell import DummyController, DummyEngine

with tempfile.TemporaryDirectory() as settings:
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings)
    qt = QApplication([])
    prefs = QSettings(str(Path(settings) / "preview.ini"), QSettings.IniFormat)
    prefs.setValue("settingsMigrated", True)
    window = app.DesktopApplication(DummyController(), DummyEngine(), settings=prefs)
    window.animations_enabled = False
    window.show()
    for width, height in [(1040, 700), (1280, 820)]:
        window.resize(width, height)
        qt.processEvents()
        qt.processEvents()
        assert window.grab().save(f"ui-preview-{width}.png")
    window._quit_application()
