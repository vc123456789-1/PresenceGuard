"""Webcam local. No hay red, grabación ni fotografías guardadas."""
import os
import ctypes
from ctypes import wintypes
import json
import sys
from pathlib import Path
import time
import cv2
import numpy as np
from guard import BlinkChallenge


def prepare(gray, low_light=True):
    if not isinstance(gray, np.ndarray) or gray.ndim != 2 or gray.size == 0:
        raise ValueError('Imagen en escala de grises inválida.')
    gray = cv2.resize(gray, (160, 160))
    if low_light:
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return cv2.equalizeHist(gray)


def inspect_frame(frame, detector, eye_detector, low_light=True):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Subir contraste no inventa detalle donde no hay luz.
    if gray.mean() < 8 or gray.std() < 5:
        return None, 'unknown'
    search = cv2.createCLAHE(2.0, (8, 8)).apply(gray) if low_light else gray
    boxes = detector.detectMultiScale(search, 1.1, 5, minSize=(80, 80))
    if len(boxes) != 1:
        return None, 'unknown'
    x, y, w, h = map(int, boxes[0])
    crop = gray[y:y+h, x:x+w]
    if crop.size == 0 or crop.mean() < 8 or crop.std() < 5:
        return None, 'unknown'
    face = cv2.resize(crop, (160, 160))
    normalized = prepare(face, low_light)
    eyes = eye_detector.detectMultiScale(normalized[:100, :], 1.1, 5,
                                         minSize=(16, 16), maxSize=(65, 65))
    centers = [(ex + ew/2, ey + eh/2) for ex, ey, ew, eh in eyes]
    left = any(24 < x < 77 and 20 < y < 85 for x, y in centers)
    right = any(83 < x < 136 and 20 < y < 85 for x, y in centers)
    state = 'open' if left and right else ('closed' if len(eyes) == 0 else 'unknown')
    return face, state


class Camera:
    def __init__(self, index, factory=None):
        self.index = index
        self.factory = factory or cv2.VideoCapture
        self.capture = None

    def __enter__(self):
        self.capture = self.factory(self.index, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
        try:
            if not self.capture.isOpened():
                raise RuntimeError('Camera unavailable. Check permissions or close other camera apps.')
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            return self.capture
        except Exception:
            self.capture.release()
            raise

    def __exit__(self, *args):
        self.capture.release()



# OpenCV's published example threshold, not calibrated for this installation.
SIMILARITY_THRESHOLD = 0.363
MODEL_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'models'
DETECTOR_FILE = 'face_detection_yunet_2023mar.onnx'
RECOGNIZER_FILE = 'face_recognition_sface_2021dec.onnx'


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Windows data protection is required for face data.')
    data = bytes(data)
    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    src = _Blob(len(data), source)
    dst = _Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(src), 'PresenceGuard face data', None, None, None, 1, ctypes.byref(dst))
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise RuntimeError('Could not protect face data for this Windows account.')
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel.LocalFree(dst.pbData)


def _valid_vector(vector):
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-9:
        raise ValueError('Invalid face data.')
    return vector


def save_embeddings(path, embeddings, enhanced=None):
    rows = [_valid_vector(item) for item in embeddings]
    enhanced_rows = [_valid_vector(item) for item in (enhanced if enhanced is not None else embeddings)]
    if not rows or len(rows) != len(enhanced_rows) or any(row.size != 128 for row in rows + enhanced_rows):
        raise ValueError('Invalid face data.')
    payload = json.dumps({'version': 2, 'model': 'sface-2021dec',
                          'normal': [row.tolist() for row in rows],
                          'enhanced': [row.tolist() for row in enhanced_rows]}, separators=(',', ':')).encode('utf-8')
    encrypted = _dpapi(payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    try:
        temporary.write_bytes(encrypted)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_embeddings(path, low_light=True):
    try:
        payload = json.loads(_dpapi(Path(path).read_bytes(), decrypt=True))
        if payload.get('version') != 2 or payload.get('model') != 'sface-2021dec':
            raise ValueError('Unsupported face data.')
        rows = [_valid_vector(row) for row in payload['enhanced' if low_light else 'normal']]
        if not 1 <= len(rows) <= 128 or any(row.size != 128 for row in rows):
            raise ValueError('Invalid face data.')
        return rows
    except (OSError, KeyError, TypeError, ValueError, UnicodeError, RuntimeError) as exc:
        raise RuntimeError('Face data is unavailable. Register your face again.') from exc


def matches_identity(vector, samples, threshold=SIMILARITY_THRESHOLD):
    vector = _valid_vector(vector)
    norm = np.linalg.norm(vector)
    if not samples:
        raise ValueError('No registered face samples.')
    scores = []
    for sample in samples:
        sample = _valid_vector(sample)
        if sample.size != vector.size:
            raise ValueError('Invalid face data.')
        scores.append(float(np.dot(vector, sample) / (norm * np.linalg.norm(sample))))
    return max(scores) >= threshold


def _enhance_color(frame, low_light):
    if not low_light:
        return frame
    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    ycrcb[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(ycrcb[:, :, 0])
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)


def extract_face(frame, detector, low_light):
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
        return None, 'unknown'
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if gray.mean() < 8 or gray.std() < 5:
        return None, 'unknown'
    processed = _enhance_color(frame, low_light)
    detector.setInputSize((frame.shape[1], frame.shape[0]))
    _, faces = detector.detect(processed)
    if faces is None or len(faces) != 1:
        return None, 'unknown'
    face = faces[0]
    x, y, width, height = [int(v) for v in face[:4]]
    x, y = max(0, x), max(0, y)
    crop = gray[y:min(y + height, gray.shape[0]), x:min(x + width, gray.shape[1])]
    if width < 80 or height < 80 or crop.size == 0 or crop.mean() < 8 or crop.std() < 5:
        return None, 'unknown'
    return processed, face


def _eyes_state(frame, face, eye_detector):
    x, y, width, height = [int(v) for v in face[:4]]
    x, y = max(0, x), max(0, y)
    crop = frame[y:y + height, x:x + width]
    if crop.size == 0:
        return 'unknown'
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    normalized = prepare(gray, True)
    eyes = eye_detector.detectMultiScale(normalized[:100, :], 1.1, 5,
                                         minSize=(16, 16), maxSize=(65, 65))
    centers = [(ex + ew/2, ey + eh/2) for ex, ey, ew, eh in eyes]
    left = any(24 < ex < 77 and 20 < ey < 85 for ex, ey in centers)
    right = any(83 < ex < 136 and 20 < ey < 85 for ex, ey in centers)
    return 'open' if left and right else ('closed' if len(eyes) == 0 else 'unknown')


def _load_models():
    detector_path = MODEL_ROOT / DETECTOR_FILE
    recognizer_path = MODEL_ROOT / RECOGNIZER_FILE
    if not detector_path.is_file() or not recognizer_path.is_file():
        raise RuntimeError('Face models are missing. Reinstall PresenceGuard.')
    try:
        detector = cv2.FaceDetectorYN.create(str(detector_path), '', (320, 240), 0.9, 0.3, 5000)
        recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), '')
        eyes = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye_tree_eyeglasses.xml')
        if eyes.empty():
            raise RuntimeError('Eye detector is missing. Reinstall PresenceGuard.')
        return detector, recognizer, eyes
    except cv2.error as exc:
        raise RuntimeError('Face models could not be loaded. Reinstall PresenceGuard.') from exc


def run_camera(kind, model_path, settings, stop, sample_event, emit, camera_factory=None):
    """Return success, rejected, or cancelled. Camera errors raise RuntimeError."""
    detector, recognizer, eye_detector = _load_models()
    model_path = Path(model_path)
    registered = [] if kind == 'enroll' else load_embeddings(model_path, settings['low_light'])
    samples = []
    enhanced_samples = []
    collecting = False
    last_sample = last_emit = 0.0
    hits = bad_frames = 0
    challenge = BlinkChallenge()
    deadline = time.monotonic() + (180 if kind == 'enroll' else 20)
    with Camera(settings['camera'], camera_factory) as capture:
        while time.monotonic() < deadline and not stop.is_set():
            ok, frame = capture.read()
            if stop.is_set():
                break
            if not ok or frame is None:
                bad_frames += 1
                if bad_frames >= 3:
                    raise RuntimeError('Camera stopped sending images.')
                stop.wait(.1)
                continue
            bad_frames = 0
            now = time.monotonic()
            processed, face = extract_face(frame, detector, settings['low_light'])
            vector = None
            if processed is not None:
                aligned = recognizer.alignCrop(processed, face)
                vector = recognizer.feature(aligned).reshape(-1)
            if kind == 'enroll':
                phase = len(samples) // 8
                if sample_event.is_set():
                    collecting = True
                    sample_event.clear()
                instructions = ('Normal light: look forward. Press Capture.',
                                'Dim light: look forward. Press Capture.',
                                'Turn your head slightly. Press Capture.')
                text = instructions[min(phase, 2)]
                if collecting:
                    text = 'Capturing: %s/24. Change your angle slightly.' % len(samples)
                    if vector is not None and now - last_sample >= .35:
                        normal = recognizer.feature(recognizer.alignCrop(frame, face)).reshape(-1)
                        enhanced = recognizer.feature(recognizer.alignCrop(_enhance_color(frame, True), face)).reshape(-1)
                        samples.append(_valid_vector(normal).copy())
                        enhanced_samples.append(_valid_vector(enhanced).copy())
                        last_sample = now
                        if len(samples) % 8 == 0:
                            collecting = False
                        if len(samples) >= 24:
                            break
            else:
                matched = vector is not None and matches_identity(vector, registered)
                hits = hits + 1 if matched else 0
                if settings['anti_photo']:
                    # why you looking at the code dawg this is not a spyware 😭
                    eyes = _eyes_state(processed, face, eye_detector) if processed is not None else 'unknown'
                    passed = challenge.step(matched, eyes, now)
                    text = 'Look ahead and blink slowly. Photo protection is experimental.'
                    if not matched:
                        text = 'Face not confirmed. Use good light and keep one face in view.'
                    if passed and hits >= 3:
                        return True, 'Face matched. Experimental blink challenge passed.'
                else:
                    text = 'Checking face...'
                    if hits >= 3:
                        return True, 'Face matched.'
            if now - last_emit >= .12:
                preview = cv2.resize(frame, (480, 360))
                encoded, buffer = cv2.imencode('.ppm', preview)
                if encoded:
                    emit(buffer.tobytes(), text)
                last_emit = now
            stop.wait(.025)
    if stop.is_set():
        return None, 'Camera check cancelled.'
    if kind == 'enroll':
        if len(samples) < 24:
            return False, 'Registration incomplete. Capture all three phases.'
        save_embeddings(model_path, samples, enhanced_samples)
        return True, 'Face registered. Images were discarded.'
    return False, 'Face not confirmed or challenge not completed.'
