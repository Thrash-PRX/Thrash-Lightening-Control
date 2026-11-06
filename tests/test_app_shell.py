import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import app


class DummyController:
    method = "lenovo_vantage_dll"

    def __init__(self):
        self.shutdown_calls = 0
        self.current_level = 0
        self.max_level = 2
        self.levels = []

    def get_status(self):
        return {
            "system_model": "TEST",
            "method_display": "Ready",
            "method": "lenovo_vantage_dll",
        }

    def shutdown(self):
        self.shutdown_calls += 1

    def set_brightness(self, level):
        self.current_level = level
        self.levels.append(level)
        return True


class DummyEngine:
    def __init__(self):
        self.running = False
        self.current_effect = None
        self.music_level = 0
        self.last_error = None
        self.idle_sleeping = False
        self.idle_seconds = 0
        self.stop_calls = 0
        self.stop_restore_values = []
        self.start_calls = []

    def start(self, effect, **kwargs):
        self.running = True
        self.current_effect = effect
        self.start_calls.append((effect, kwargs))

    def stop(self, restore=True):
        self.stop_calls += 1
        self.stop_restore_values.append(restore)
        self.running = False


class DesktopShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings_directory = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_directory.name)
        cls.qt_app = QApplication.instance() or QApplication([])
        cls.qt_app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.settings_directory.cleanup()

    def make_window(self, controller, engine):
        return app.DesktopApplication(controller, engine, settings=self.settings_store())

    def settings_store(self):
        return QSettings(os.path.join(self.settings_directory.name, "preferences.ini"), QSettings.IniFormat)

    def test_keyboard_preview_follows_cached_native_state_without_hardware_poll(self):
        controller = DummyController()
        window = self.make_window(controller, DummyEngine())
        window.show()
        for level in (0, 1, 2, 0):
            controller.current_level = level
            window._refresh_keyboard_preview()
            self.assertEqual(window.keyboard_preview.level, level)
            self.assertTrue(window.keyboard_preview.available)
        controller.max_level = 1
        controller.current_level = 1
        window._refresh_keyboard_preview()
        self.assertEqual(window.keyboard_preview.maximum, 1)
        controller.method = 'unavailable'
        window._refresh_keyboard_preview()
        self.assertFalse(window.keyboard_preview.available)
        self.assertFalse(controller.levels)
        window._quit_application()

    def test_keyboard_preview_contains_distinct_numpad_and_single_zone(self):
        keys = app.LOQKeyboardPreview.key_layout()
        self.assertGreater(len(keys), 95)
        self.assertTrue(any(label == 'Enter' and x > 15 and height == 2 for label,x,y,width,height in keys))
        window = self.make_window(DummyController(), DummyEngine())
        window.keyboard_preview.set_native_state(2, 2, True)
        self.assertIn('Bright', window.keyboard_preview.accessibleDescription())
        window._quit_application()

    def test_native_presets_start_steady_and_dashboard_tracks_power(self):
        engine = DummyEngine()
        window = self.make_window(DummyController(), engine)
        window._native_preset(100)
        window._refresh_status()
        self.assertEqual(window.selected_effect(), "steady")
        self.assertEqual(engine.start_calls[-1][0], "steady")
        self.assertEqual(window.intensity_slider.value(), 100)
        self.assertIn("Steady", window.lighting_summary.text())
        window.toggle_power()
        window._refresh_status()
        self.assertIn("Off", window.lighting_summary.text())
        window._quit_application()

    def test_close_hides_to_tray_and_quit_cleans_up(self):
        controller = DummyController()
        engine = DummyEngine()
        window = self.make_window(controller, engine)
        window._tray_notice_shown = True
        window.show()
        self.qt_app.processEvents()

        with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
            window.close()
            self.qt_app.processEvents()

        self.assertFalse(window.isVisible())
        self.assertEqual(engine.stop_calls, 0)
        self.assertEqual(controller.shutdown_calls, 0)

        window._quit_application()
        self.assertEqual(engine.stop_calls, 1)
        self.assertEqual(controller.shutdown_calls, 1)

    def test_startup_state_requires_task_and_task_manager_entry(self):
        with patch.object(app, "_startup_task_exists", return_value=True), patch.object(
            app, "_startup_registry_enabled", return_value=True
        ):
            self.assertTrue(app.startup_task_enabled())
        with patch.object(app, "_startup_task_exists", return_value=True), patch.object(
            app, "_startup_registry_enabled", return_value=False
        ):
            self.assertFalse(app.startup_task_enabled())

    def test_enabling_startup_creates_task_before_run_entry(self):
        calls = []
        with patch.object(app, "_create_startup_task", side_effect=lambda: calls.append("task")), patch.object(
            app, "_set_startup_registry", side_effect=lambda enabled: calls.append(f"run:{enabled}")
        ):
            app.set_startup_task(True)
        self.assertEqual(calls, ["task", "run:True"])

    def test_normal_mode_hides_all_advanced_controls(self):
        window = self.make_window(DummyController(), DummyEngine())
        window.god_checkbox.setChecked(False)
        self.qt_app.processEvents()
        self.assertTrue(all(widget.isHidden() for widget in window.advanced_widgets))
        window._quit_application()

    def test_startup_battery_saver_starts_asleep(self):
        controller = DummyController()
        controller.levels = []
        controller.set_brightness = lambda level: controller.levels.append(level) or True
        engine = DummyEngine()
        window = self.make_window(controller, engine)
        window.arm_startup_battery_saver()
        self.assertEqual(controller.levels[-1], 0)
        self.assertEqual(engine.start_calls[-1][0], "battery_saver")
        self.assertTrue(engine.start_calls[-1][1]["start_asleep"])
        window._quit_application()

    def test_effect_cards_switch_immediately_with_one_click(self):
        engine = DummyEngine()
        controller = DummyController()
        window = self.make_window(controller, engine)
        window.cards["breathe"].click()
        self.assertEqual(engine.start_calls[-1][0], "breathe")
        window.cards["wave"].click()
        self.assertEqual(engine.start_calls[-1][0], "wave")
        self.assertEqual([call[0] for call in engine.start_calls[-2:]], ["breathe", "wave"])
        self.assertEqual(engine.stop_calls, 0)
        self.assertNotIn(0, controller.levels)
        self.assertTrue(window.power_button.property("powered"))
        window._quit_application()

    def test_selecting_effect_while_powered_off_starts_in_one_click(self):
        controller = DummyController()
        engine = DummyEngine()
        window = self.make_window(controller, engine)
        window.cards["breathe"].click()
        window.toggle_power()
        self.assertFalse(engine.running)
        controller.levels.clear()

        window.cards["wave"].click()

        self.assertTrue(engine.running)
        self.assertEqual(engine.start_calls[-1][0], "wave")
        self.assertTrue(window.power_button.property("powered"))
        self.assertNotIn(0, controller.levels)
        window._quit_application()

    def test_header_fits_full_title_at_minimum_and_normal_width(self):
        window = self.make_window(DummyController(), DummyEngine())
        window.show()

        for width in (1040, 1280):
            window.resize(width, 700)
            self.qt_app.processEvents()
            self.qt_app.processEvents()
            metrics = QFontMetrics(window.header_title.font())
            required = metrics.horizontalAdvance(window.header_title.text())
            available = window.header_title.contentsRect().width()
            self.assertLessEqual(required, available + 1, f"title clipped at {width}px")
            self.assertGreaterEqual(window.header_title.font().pointSizeF(), 15)
            self.assertGreaterEqual(window.header_title.height(), metrics.height())
            self.assertLessEqual(
                window.header_panel.minimumSizeHint().width(),
                window.header_panel.width(),
            )
            self.assertTrue(window.power_button.isVisible())
            self.assertLessEqual(
                window.power_button.geometry().right(),
                window.header_panel.contentsRect().right(),
            )

        window._quit_application()

    def test_god_mode_reactive_choices_and_speed_apply_live(self):
        engine = DummyEngine()
        window = self.make_window(DummyController(), engine)
        window.god_mode = True
        window._apply_god_mode()
        window.cards["reactive"].click()

        window.react_buttons.button(5).click()
        window.hold_buttons.button(1).click()

        self.assertEqual(engine.mode, 5)
        self.assertEqual(engine.hold_behavior, 1)
        self.assertEqual(window.speed_slider.maximum(), 20)
        window.speed_slider.setValue(20)
        self.assertEqual(engine.speed, 2.0)

        window.cards["breathe"].click()
        self.assertEqual(window.speed_slider.maximum(), 16)
        self.assertLessEqual(engine.start_calls[-1][1]["speed"], 1.6)
        window._quit_application()

    def test_shell_uses_translucent_glass_surfaces(self):
        window = self.make_window(DummyController(), DummyEngine())
        self.assertIsInstance(window.header_panel, app.GlassFrame)
        self.assertIsInstance(window.sidebar_panel, app.GlassFrame)
        glass_surfaces = window.findChildren(app.GlassFrame)
        self.assertGreaterEqual(len(glass_surfaces), 5)
        self.assertTrue(
            all(surface.testAttribute(Qt.WA_TranslucentBackground) for surface in glass_surfaces)
        )
        self.assertFalse(window.background._texture.isNull())
        window._quit_application()

    def test_top_right_power_turns_keyboard_fully_off(self):
        controller = DummyController()
        engine = DummyEngine()
        window = self.make_window(controller, engine)
        window.cards["breathe"].click()
        window.toggle_power()
        self.assertFalse(engine.running)
        self.assertEqual(controller.current_level, 0)
        self.assertFalse(window.power_button.property("powered"))
        window._quit_application()


    def test_tray_effect_switching_works_without_opening_window(self):
        controller = DummyController()
        engine = DummyEngine()
        window = self.make_window(controller, engine)
        self.assertFalse(window.isVisible())

        window.tray_effect_actions["wave"].trigger()
        self.assertEqual(window.selected_effect(), "wave")
        self.assertEqual(engine.start_calls[-1][0], "wave")
        self.assertTrue(window.tray_effect_actions["wave"].isChecked())
        self.assertEqual(window.tray_power_action.text(), "Turn Lighting Off")

        window.tray_effect_actions["reactive"].trigger()
        self.assertEqual(engine.start_calls[-1][0], "reactive")
        self.assertFalse(window.tray_effect_actions["wave"].isChecked())
        self.assertTrue(window.tray_effect_actions["reactive"].isChecked())

        window.toggle_power()
        self.assertEqual(window.tray_power_action.text(), "Turn Lighting On")
        self.assertFalse(any(action.isChecked() for action in window.tray_effect_actions.values()))
        window._quit_application()

    def test_remembers_selected_effect_without_auto_start(self):
        settings = self.settings_store()
        had_value = settings.contains("lastEffect")
        previous = settings.value("lastEffect")
        try:
            settings.setValue("lastEffect", "wave")
            engine = DummyEngine()
            window = self.make_window(DummyController(), engine)
            self.assertEqual(window.selected_effect(), "wave")
            self.assertFalse(engine.start_calls)

            window.cards["breathe"].click()
            self.assertEqual(settings.value("lastEffect"), "breathe")
            window._quit_application()

            settings.setValue("lastEffect", "nonexistent")
            fallback = self.make_window(DummyController(), DummyEngine())
            self.assertEqual(fallback.selected_effect(), "battery_saver")
            fallback._quit_application()
        finally:
            if had_value:
                settings.setValue("lastEffect", previous)
            else:
                settings.remove("lastEffect")

if __name__ == "__main__":
    unittest.main()
