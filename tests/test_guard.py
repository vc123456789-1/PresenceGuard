"""Pruebas sin webcam, sin PIN real y sin llamar a LockWorkStation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

if importlib.util.find_spec('guard'):
    import guard
else:
    guard = None


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(guard, 'Falta implementar guard.py')

    def test_requested_defaults(self):
        s = guard.DEFAULTS
        self.assertEqual(s['interval_seconds'], 180)
        for key in ('low_light', 'anti_photo'):
            self.assertIs(s[key], True)
        self.assertIs(s['startup'], False)
        self.assertNotIn('agents_enabled', s)
        self.assertNotIn('agent_minutes', s)
        self.assertNotIn('armed', s)

    def test_interval_units(self):
        self.assertEqual(guard.seconds('3', 'minutes'), 180)
        self.assertEqual(guard.seconds('0,5', 'hours'), 1800)
        self.assertEqual(guard.seconds('15', 'seconds'), 15)

    def test_keep_awake_duration_defaults_and_round_trip(self):
        from guard import load_settings, write_json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            settings = load_settings(path)
            self.assertEqual(settings['awake_duration'], 30)
            self.assertEqual(settings['awake_unit'], 'minutes')
            settings['awake_duration'] = 45
            settings['awake_unit'] = 'seconds'
            write_json(path, settings)
            restored = load_settings(path)
            self.assertEqual(restored['awake_duration'], 45)
            self.assertEqual(restored['awake_unit'], 'seconds')

    def test_invalid_saved_awake_duration_is_rejected(self):
        from guard import load_settings, write_json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for duration, unit in ((0, 'seconds'), (25, 'hours'), ('nan', 'minutes'), (1, 'days')):
                with self.subTest(duration=duration, unit=unit):
                    write_json(path, {'awake_duration': duration, 'awake_unit': unit})
                    with self.assertRaises(ValueError):
                        load_settings(path)

    def test_bad_interval(self):
        for value in ('', 'nan', 'inf', '-1', '0', 'abc', '999999'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                guard.seconds(value, 'segundos')
        with self.assertRaises(ValueError):
            guard.seconds('2', 'semanas')

    def test_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'settings.json'
            guard.write_json(p, guard.DEFAULTS)
            self.assertEqual(guard.load_settings(p), guard.DEFAULTS)

    def test_corrupt_settings_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'settings.json'
            p.write_text('{broken', encoding='utf-8')
            with self.assertRaises(ValueError):
                guard.load_settings(p)
            p.write_text('{"low_light":"false"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                guard.load_settings(p)

    def test_pin_salt_and_verification(self):
        a = guard.pin_record('01234567')
        b = guard.pin_record('01234567')
        self.assertNotEqual(a['salt'], b['salt'])
        self.assertNotIn('01234567', json.dumps(a))
        self.assertTrue(guard.verify_pin(a, '01234567'))
        self.assertFalse(guard.verify_pin(a, '98765432'))
        self.assertFalse(guard.verify_pin({}, '01234567'))

    def test_pin_validation(self):
        for pin in ('', '123', 'abcdef', '1234567890123', '\u0661\u0662\u0663\u0664\u0665\u0666'):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                guard.pin_record(pin)

    def test_pin_cooldown_persists(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'pin.json'
            gate = guard.PinGate(p)
            gate.create('01234567')
            for now in (100, 101, 102):
                self.assertFalse(gate.check('99999999', now=now))
            self.assertFalse(guard.PinGate(p).check('01234567', now=106))
            self.assertFalse(gate.check('99999999', now=107))
            self.assertFalse(guard.PinGate(p).check('01234567', now=116))
            self.assertTrue(guard.PinGate(p).check('01234567', now=117))
            self.assertEqual(gate.read()['failures'], 0)
            with self.assertRaises(ValueError):
                gate.create('98765432')

    def test_pin_corruption_does_not_allow_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'pin.json'
            p.write_text('broken')
            gate = guard.PinGate(p)
            self.assertTrue(gate.exists())
            with self.assertRaises(ValueError):
                gate.check('01234567', now=0)
            with self.assertRaises(ValueError):
                gate.create('01234567')

    def test_no_real_lock_by_default(self):
        p = guard.Policy()
        self.assertFalse(p.armed)
        p.start()
        self.assertEqual(p.result(False, 10), 'retry')
        self.assertEqual(p.result(False, 20), 'grace')
        self.assertIsNone(p.action(34.9))
        self.assertEqual(p.action(35), 'simulate_lock')
        self.assertIsNone(p.action(36))

    def test_manual_test_never_locks(self):
        p = guard.Policy()
        p.start()
        for _ in range(5):
            self.assertEqual(p.result(False, 10, automatic=False), 'test_fail')
        self.assertIsNone(p.action(100))
        self.assertEqual(p.failures, 0)

    def test_arm_needs_tests_and_confirmation(self):
        p = guard.Policy()
        with self.assertRaises(ValueError):
            p.arm(True)
        p.result(True, 10, automatic=False)
        with self.assertRaises(ValueError):
            p.arm(False)
        p.arm(True)
        self.assertTrue(p.armed)
        p.start()
        p.result(False, 10)
        p.result(False, 20)
        self.assertEqual(p.action(35), 'lock')

    def test_stop_cancels_grace_and_disarms(self):
        p = guard.Policy()
        p.start()
        p.result(False, 0)
        p.result(False, 1)
        p.stop()
        self.assertIsNone(p.action(100))
        self.assertFalse(p.armed)

    def test_stop_clears_pause_before_next_start(self):
        p = guard.Policy()
        p.start()
        p.pause(30, 10)
        p.stop()
        p.start()
        self.assertFalse(p.paused(11))

    def test_explicit_pause_expires(self):
        p = guard.Policy()
        p.start()
        p.pause(1, 10)
        self.assertTrue(p.paused(69.9))
        self.assertFalse(p.paused(70))
        self.assertEqual(p.result(False, 20), 'ignored')
        self.assertEqual(p.result(False, 71), 'retry')
        with self.assertRaises(ValueError):
            p.pause(241, 0)

    def test_explicit_pause_cancels_pending_lock(self):
        p = guard.Policy()
        p.start()
        p.result(False, 0)
        p.result(False, 1)
        p.pause(30, 2)
        self.assertIsNone(p.action(20))
        self.assertIsNone(p.action(2000))

    def test_success_clears_failures(self):
        p = guard.Policy()
        p.start()
        p.result(False, 0)
        p.result(False, 1)
        self.assertEqual(p.result(True, 2), 'ok')
        self.assertIsNone(p.action(100))

    def test_static_eyes_do_not_pass_challenge(self):
        for state in ('open', 'closed', 'unknown'):
            challenge = guard.BlinkChallenge(goal=1)
            for i in range(100):
                self.assertFalse(challenge.step(True, state, i / 10))

    def test_guided_blink_passes(self):
        c = guard.BlinkChallenge(goal=1)
        states = ['open']*6 + ['closed']*3 + ['open']*6
        results = [c.step(True, s, i/10) for i, s in enumerate(states)]
        self.assertTrue(results[-1])

    def test_unknown_or_face_loss_resets_challenge(self):
        for matched, state in ((False, 'open'), (True, 'unknown')):
            c = guard.BlinkChallenge(goal=1)
            for i in range(6):
                c.step(True, 'open', i/10)
            c.step(matched, state, .6)
            for i in range(3):
                c.step(True, 'closed', .7+i/10)
            for i in range(6):
                self.assertFalse(c.step(True, 'open', 1+i/10))

    def test_long_closed_eyes_do_not_pass(self):
        c = guard.BlinkChallenge(goal=1)
        for i in range(6):
            c.step(True, 'open', i/10)
        for i in range(15):
            c.step(True, 'closed', .6+i/10)
        for i in range(6):
            self.assertFalse(c.step(True, 'open', 2.1+i/10))


if __name__ == '__main__':
    unittest.main()
