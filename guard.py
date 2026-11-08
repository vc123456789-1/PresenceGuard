"""Testable rules. This module does not access the camera or lock Windows."""
import hashlib
import hmac
import json
import math
from pathlib import Path
import secrets
import time

DEFAULTS = dict(interval_seconds=180.0, low_light=True, anti_photo=True,
                startup=False, camera=0, awake_duration=30.0, awake_unit='minutes')
ITERATIONS = 600_000


def seconds(value, unit='seconds'):
    try:
        amount = float(str(value).replace(',', '.'))
        result = amount * {'seconds': 1, 'minutes': 60, 'hours': 3600,
                           'segundos': 1, 'minutos': 60, 'horas': 3600}[unit]
    except (ValueError, TypeError, KeyError):
        raise ValueError('Enter a number and choose seconds, minutes or hours.') from None
    if not math.isfinite(result) or not 1 <= result <= 86400:
        raise ValueError('Choose an interval from 1 second to 24 hours.')
    return result


def awake_seconds(value, unit):
    if unit not in ('seconds', 'minutes', 'hours'):
        raise ValueError('Choose seconds, minutes or hours.')
    try:
        return seconds(value, unit)
    except ValueError:
        raise ValueError('Choose a duration from 1 second to 24 hours.') from None


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def load_settings(path):
    path = Path(path)
    result = DEFAULTS.copy()
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(saved, dict):
                raise ValueError('Invalid settings format.')
            result.update({key: saved[key] for key in DEFAULTS if key in saved})
        except (OSError, ValueError) as exc:
            raise ValueError('Could not read settings.') from exc
    result['interval_seconds'] = seconds(result['interval_seconds'])
    awake_seconds(result['awake_duration'], result['awake_unit'])
    result['awake_duration'] = float(str(result['awake_duration']).replace(',', '.'))
    for key in ('low_light', 'anti_photo', 'startup'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid setting: ' + key)
    if type(result['camera']) is not int or not 0 <= result['camera'] <= 10:
        raise ValueError('Choose a camera from 0 to 10.')
    return result


def pin_record(pin):
    if not isinstance(pin, str) or not pin.isascii() or not pin.isdigit() or not 6 <= len(pin) <= 12:
        raise ValueError('Choose a PIN with 6 to 12 digits.')
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', pin.encode('ascii'), salt, ITERATIONS)
    return dict(salt=salt.hex(), digest=digest.hex(), iterations=ITERATIONS)


def verify_pin(record, pin):
    try:
        if record['iterations'] != ITERATIONS or not isinstance(pin, str):
            return False
        salt = bytes.fromhex(record['salt'])
        expected = bytes.fromhex(record['digest'])
        if len(salt) != 16 or len(expected) != 32 or len(pin) > 12:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt, ITERATIONS)
        return hmac.compare_digest(actual, expected)
    except (KeyError, TypeError, ValueError):
        return False


class PinGate:
    """Protect the interface, not the account or application files."""
    def __init__(self, path):
        self.path = Path(path)

    def exists(self):
        return self.path.exists()

    def create(self, pin):
        if self.exists():
            raise ValueError('A PIN already exists.')
        self.replace(pin)

    def replace(self, pin):
        # Solo llamar después de verificar el PIN anterior, o en el primer registro.
        record = pin_record(pin)
        record.update(failures=0, blocked_until=0)
        write_json(self.path, record)

    def read(self):
        try:
            record = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(record, dict) or record.get('iterations') != ITERATIONS:
                raise ValueError('Formato incorrecto.')
            if len(bytes.fromhex(record['salt'])) != 16 or len(bytes.fromhex(record['digest'])) != 32:
                raise ValueError('Hash incorrecto.')
            if type(record.get('failures')) is not int or not 0 <= record['failures'] <= 9:
                raise ValueError('Contador incorrecto.')
            until = record.get('blocked_until')
            if type(until) not in (int, float) or not math.isfinite(until) or until < 0:
                raise ValueError('Espera incorrecta.')
            return record
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError('The PIN file is damaged. It will not be reset automatically.') from exc

    def check(self, pin, now=None):
        now = time.time() if now is None else now
        record = self.read()
        if now < record['blocked_until']:
            return False
        if verify_pin(record, pin):
            record.update(failures=0, blocked_until=0)
            write_json(self.path, record)
            return True
        record['failures'] = min(9, record['failures'] + 1)
        if record['failures'] >= 3:
            record['blocked_until'] = now + min(300, 5 * 2 ** (record['failures'] - 3))
        write_json(self.path, record)
        return False


class Policy:
    """A lock result is a decision, never an operating-system call."""
    def __init__(self):
        self.running = False
        self.armed = False
        self.failures = 0
        self.checks = 0
        self.grace_until = None
        self.pause_until = 0.0

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        self.armed = False
        self.pause_until = 0.0
        self.clear()

    def clear(self):
        self.failures = 0
        self.grace_until = None

    def paused(self, now):
        return now < self.pause_until

    def pause(self, minutes, now):
        value = float(minutes)
        if not math.isfinite(value) or not 1 <= value <= 240:
            raise ValueError('Choose a pause from 1 to 240 minutes.')
        self.pause_until = now + 60 * value
        self.clear()

    def arm(self, confirmed=False):
        if not confirmed or self.checks < 1:
            raise ValueError('Complete a successful test and confirm first.')
        self.armed = True

    def result(self, success, now, automatic=True):
        if not automatic:
            if success:
                self.checks += 1
            else:
                self.checks = 0
            return 'test_ok' if success else 'test_fail'
        if not self.running or self.paused(now):
            return 'ignored'
        if success:
            self.clear()
            return 'ok'
        self.failures += 1
        if self.failures == 1:
            return 'retry'
        self.grace_until = now + 15
        return 'grace'

    def action(self, now):
        if not self.running or self.paused(now) or self.grace_until is None or now < self.grace_until:
            return None
        self.clear()
        return 'lock' if self.armed else 'simulate_lock'


class BlinkChallenge:
    """Heurística de ojos abiertos/cerrados. NO es prueba de vida robusta."""
    def __init__(self, goal=None):
        self.goal = secrets.choice((1, 2)) if goal is None else goal
        self.reset()

    def reset(self):
        self.phase = 'open'
        self.since = None
        self.last = None
        self.count = 0

    def step(self, matched, eyes, now):
        if not matched or eyes not in ('open', 'closed'):
            self.reset()
            return False
        if self.last is not None and (now < self.last or now - self.last > .5):
            self.reset()
        self.last = now
        if self.count >= self.goal:
            return True
        if self.phase == 'open':
            if eyes != 'open':
                self.since = None
            elif self.since is None:
                self.since = now
            elif now - self.since >= .3 - 1e-9:
                self.phase, self.since = 'close', None
        elif self.phase == 'close':
            if eyes == 'closed':
                if self.since is None:
                    self.since = now
                elif now - self.since > .8:
                    self.reset()
            elif self.since is not None:
                if .12 <= now - self.since <= .8:
                    self.phase, self.since = 'reopen', now
                else:
                    self.reset()
        elif self.phase == 'reopen':
            if eyes != 'open':
                self.reset()
            elif now - self.since >= .25 - 1e-9:
                self.count += 1
                self.phase, self.since = 'open', now
        return self.count >= self.goal
