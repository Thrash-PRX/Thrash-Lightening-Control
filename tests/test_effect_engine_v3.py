import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app


class RecordingController:
    def __init__(self):
        self.current_level = 0
        self.max_level = 2
        self.levels = []

    def set_brightness(self, level):
        self.current_level = level
        self.levels.append(level)
        return True


class EffectEngineV3Tests(unittest.TestCase):
    def test_public_modes_exclude_retired_flash_modes(self):
        ids = {effect["id"] for effect in app.EffectEngine.EFFECTS_META}
        self.assertTrue({"battery_saver", "breathe", "reactive", "music_speaker"} <= ids)
        self.assertTrue({"blink", "strobe", "sos", "lightning", "candle", "heartbeat", "disco", "pulse", "binary"}.isdisjoint(ids))

    def test_constant_intensity_does_not_toggle_native_states(self):
        controller = RecordingController()
        engine = app.EffectEngine(controller)
        levels = [engine._render_intensity(75) for _ in range(120)]
        self.assertEqual(len(set(levels)), 1)
        self.assertLessEqual(len(controller.levels), 1)

    def test_hysteresis_suppresses_boundary_chatter_and_off_is_exact(self):
        controller = RecordingController()
        engine = app.EffectEngine(controller)
        for value in [50, 74, 76, 74, 76]:
            engine._render_intensity(value)
        self.assertEqual(controller.levels, [1])
        engine._render_intensity(100)
        engine._render_intensity(0)
        self.assertEqual(controller.levels[-2:], [2, 0])

    def test_one_level_keyboard_never_receives_bright_state(self):
        controller = RecordingController()
        controller.max_level = 1
        engine = app.EffectEngine(controller)
        for value in range(101):
            engine._render_intensity(value)
        self.assertEqual(controller.levels, [1])

    def test_steady_uses_native_dim_without_repeated_writes(self):
        controller = RecordingController()
        engine = app.EffectEngine(controller)
        engine.intensity = 50
        with patch.object(engine, "_wait", return_value=False):
            for _ in range(10):
                engine._steady()
        self.assertEqual(controller.levels, [1])

    def test_recommended_speed_is_used_without_god_mode_override(self):
        controller = RecordingController()
        engine = app.EffectEngine(controller)
        engine._start_keyboard_hook = lambda: True
        engine._loop = lambda: None
        engine.start("reactive", intensity=73)
        self.assertEqual(engine.intensity, 73)
        self.assertEqual(engine.speed, app.EffectEngine.RECOMMENDED_SPEEDS["reactive"])
        engine.stop(restore=False)

    def test_battery_saver_defaults_to_thirty_seconds(self):
        engine = app.EffectEngine(RecordingController())
        self.assertEqual(engine.idle_timeout, 30.0)

    def test_battery_saver_mouse_activity_wakes_and_resets_idle_timer(self):
        engine = app.EffectEngine(RecordingController())
        engine.running = True
        engine.intensity = 64
        engine.idle_sleeping = True
        engine._idle_started = 1.0
        engine._last_input_tick = 100

        with patch.object(engine, "_get_last_input_tick", return_value=101), patch.object(
            app.time, "monotonic", return_value=40.0
        ), patch.object(engine, "_fade_to", return_value=False) as fade, patch.object(
            engine, "_wait", return_value=True
        ):
            engine._battery_saver()

        self.assertFalse(engine.idle_sleeping)
        self.assertEqual(engine.idle_seconds, 0.0)
        self.assertEqual(engine._idle_started, 40.0)
        fade.assert_called_once_with(64, 0.68, start=0)

    def test_battery_saver_unchanged_system_input_does_not_reset_idle(self):
        engine = app.EffectEngine(RecordingController())
        engine.running = True
        engine.idle_timeout = 30.0
        engine._idle_started = 0.0
        engine._last_input_tick = 100

        with patch.object(engine, "_get_last_input_tick", return_value=100), patch.object(
            app.time, "monotonic", return_value=31.0
        ), patch.object(engine, "_fade_to", return_value=False) as fade, patch.object(
            engine, "_wait", return_value=True
        ):
            engine._battery_saver()

        self.assertTrue(engine.idle_sleeping)
        fade.assert_called_once_with(0, 0.48)

    def test_breathe_curve_has_soft_symmetric_shoulders(self):
        samples = [app.EffectEngine._breathe_envelope(i / 100) for i in range(101)]
        self.assertAlmostEqual(samples[0], 0.0)
        self.assertAlmostEqual(samples[50], 1.0)
        self.assertAlmostEqual(samples[-1], 0.0, places=8)
        self.assertTrue(all(a <= b for a, b in zip(samples[:50], samples[1:51])))
        self.assertTrue(all(a >= b for a, b in zip(samples[50:100], samples[51:])))
        self.assertLess(max(abs(b - a) for a, b in zip(samples, samples[1:])), 0.04)

    def test_wave_curve_is_materially_different_from_breathe(self):
        phases = [index / 100 for index in range(101)]
        breathe = [app.EffectEngine._breathe_envelope(phase) for phase in phases]
        wave = [app.EffectEngine._wave_envelope(phase) for phase in phases]

        breathe_peak = max(range(len(breathe)), key=breathe.__getitem__) / 100
        wave_peak = max(range(len(wave)), key=wave.__getitem__) / 100
        mean_difference = sum(abs(a - b) for a, b in zip(breathe, wave)) / len(phases)

        self.assertGreaterEqual(breathe_peak, 0.45)
        self.assertLessEqual(breathe_peak, 0.55)
        self.assertGreaterEqual(wave_peak, 0.08)
        self.assertLessEqual(wave_peak, 0.30)
        self.assertGreater(mean_difference, 0.25)
        self.assertGreater(
            app.EffectEngine._wave_envelope(0.78),
            app.EffectEngine._wave_envelope(0.68) + 0.20,
        )

    def test_god_mode_speed_limits_protect_smooth_effects(self):
        self.assertEqual(app.EffectEngine.clamp_speed("breathe", 9.0), 1.65)
        self.assertEqual(app.EffectEngine.clamp_speed("wave", 9.0), 2.20)
        self.assertEqual(app.EffectEngine.clamp_speed("reactive", 9.0), 2.00)
        self.assertEqual(app.EffectEngine.clamp_speed("breathe", 0.01), 0.45)

    def test_key_identity_ignores_repeat_and_releases_after_last_key(self):
        engine = app.EffectEngine(RecordingController())
        key_a = (0x41, 30, 0)
        key_b = (0x41, 48, 1)

        self.assertTrue(engine._record_key_down(key_a, 0x41))
        self.assertFalse(engine._record_key_down(key_a, 0x41))
        self.assertEqual(engine._keypress_counter, 1)
        self.assertTrue(engine._record_key_down(key_b, 0x41))
        self.assertEqual(engine._keypress_counter, 2)

        engine._keyrelease_event.clear()
        self.assertFalse(engine._record_key_up(key_a))
        self.assertFalse(engine._keyrelease_event.is_set())
        self.assertTrue(engine._record_key_up(key_b))
        self.assertTrue(engine._keyrelease_event.is_set())

    def _run_reactive_scenario(self, hold_behavior, release_at=None, stop_at=0.70):
        """Drive Reactive with a deterministic clock and no worker thread."""
        engine = app.EffectEngine(RecordingController())
        engine.running = True
        engine.mode = 2
        engine.intensity = 80
        engine.speed = 2.0
        engine.hold_behavior = hold_behavior
        engine._keypress_counter = 1
        engine._pressed_keys = {(0x41, 30, 0)}

        now = [0.0]
        rendered = []

        def monotonic():
            return now[0]

        def wait(duration):
            now[0] += duration
            if release_at is not None and now[0] >= release_at:
                with engine._keys_lock:
                    engine._pressed_keys.clear()
            if now[0] >= stop_at:
                engine.running = False
                return True
            return False

        def render(value):
            rendered.append((now[0], value))
            return 0

        with patch.object(app.time, "monotonic", side_effect=monotonic), patch.object(
            engine, "_wait", side_effect=wait
        ), patch.object(engine, "_render_intensity", side_effect=render):
            engine._reactive()

        return rendered

    def test_reactive_hold_stays_active_until_key_release(self):
        rendered = self._run_reactive_scenario(hold_behavior=2, release_at=0.30)
        active_times = [timestamp for timestamp, value in rendered if value == 80]

        self.assertGreater(len(active_times), 20)
        self.assertGreaterEqual(max(active_times), 0.30)
        self.assertTrue(any(timestamp > 0.31 and value < 80 for timestamp, value in rendered))

    def test_reactive_single_pulse_finishes_while_key_remains_held(self):
        rendered = self._run_reactive_scenario(hold_behavior=1, release_at=None)
        active_times = [timestamp for timestamp, value in rendered if value == 80]
        first_fade = min(
            timestamp
            for timestamp, value in rendered
            if timestamp > 0 and 29 < value < 80
        )

        self.assertGreaterEqual(max(active_times), 0.14)
        self.assertLess(first_fade, 0.25)


    def test_vantage_discovery_falls_back_to_newest_complete_addin(self):
        older = os.path.join("Vantage", "1.9.0", "KeyboardContract.dll")
        newer = os.path.join("Vantage", "2.0.0", "KeyboardContract.dll")
        folder = os.path.dirname(older)
        available = {older, os.path.join(folder, "IdeaNotebookAddin.dll"),
                     os.path.join(folder, "Newtonsoft.Json.dll")}
        with patch.object(app.glob, "glob", return_value=[older, newer]), patch.object(
            app.os.path, "isfile", side_effect=lambda path: path in available
        ):
            self.assertEqual(app.find_lenovo_dlls()["contract"], older)

    def test_vantage_discovery_rejects_incomplete_only_addin(self):
        contract = os.path.join("Vantage", "2.0.0", "KeyboardContract.dll")
        with patch.object(app.glob, "glob", return_value=[contract]), patch.object(
            app.os.path, "isfile", side_effect=lambda path: path == contract
        ):
            self.assertIsNone(app.find_lenovo_dlls())

if __name__ == "__main__":
    unittest.main()
