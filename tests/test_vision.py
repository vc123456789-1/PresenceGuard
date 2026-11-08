import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
import cv2
import numpy as np

if importlib.util.find_spec('vision'):
    import vision
else:
    vision = None


class FakeDetector:
    def __init__(self, boxes):
        self.boxes = boxes
    def detectMultiScale(self, *args, **kwargs):
        return self.boxes


class FakeCamera:
    def __init__(self, opened=True, fail=False, cancel=None):
        self.opened, self.fail, self.cancel = opened, fail, cancel
        self.released = False
    def isOpened(self):
        return self.opened
    def set(self, *args):
        return True
    def read(self):
        if self.cancel:
            self.cancel.set()
        return (False, None) if self.fail else (True, np.zeros((240, 320, 3), np.uint8))
    def release(self):
        self.released = True


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(vision, 'Falta implementar vision.py')
        self.gray = np.tile(np.arange(160, dtype=np.uint8), (160, 1))

    def test_low_light_has_correct_shape_and_type(self):
        dim = (self.gray * .25).astype(np.uint8)
        enhanced = vision.prepare(dim, True)
        self.assertEqual(enhanced.shape, (160, 160))
        self.assertEqual(enhanced.dtype, np.uint8)
        self.assertGreater(enhanced.std(), dim.std())

    def test_normal_mode_and_invalid_image(self):
        self.assertEqual(vision.prepare(self.gray, False).shape, (160, 160))
        with self.assertRaises(ValueError):
            vision.prepare(np.zeros((0, 0), np.uint8), True)

    def test_dark_frame_is_not_identified(self):
        frame = np.zeros((240, 320, 3), np.uint8)
        face, eyes = vision.inspect_frame(frame, FakeDetector([(0, 0, 160, 160)]), FakeDetector([]), True)
        self.assertIsNone(face)
        self.assertEqual(eyes, 'unknown')

    def test_two_faces_rejected(self):
        frame = cv2.cvtColor(self.gray, cv2.COLOR_GRAY2BGR)
        face, _ = vision.inspect_frame(frame, FakeDetector([(0, 0, 80, 80), (80, 0, 80, 80)]), FakeDetector([]), True)
        self.assertIsNone(face)

    def test_eye_state_needs_two_separate_eyes(self):
        frame = cv2.cvtColor(self.gray, cv2.COLOR_GRAY2BGR)
        detector = FakeDetector([(0, 0, 160, 160)])
        for boxes, expected in (([], 'closed'), ([(30, 30, 20, 20)], 'unknown'),
                                ([(30, 30, 20, 20), (105, 30, 20, 20)], 'open')):
            _, state = vision.inspect_frame(frame, detector, FakeDetector(boxes), True)
            self.assertEqual(state, expected)

    def test_camera_released_on_normal_exit(self):
        fake = FakeCamera()
        with vision.Camera(0, factory=lambda *a: fake):
            pass
        self.assertTrue(fake.released)

    def test_camera_released_if_open_fails(self):
        fake = FakeCamera(opened=False)
        with self.assertRaises(RuntimeError):
            with vision.Camera(0, factory=lambda *a: fake):
                pass
        self.assertTrue(fake.released)

    def test_camera_released_on_exception(self):
        fake = FakeCamera()
        with self.assertRaises(RuntimeError):
            with vision.Camera(0, factory=lambda *a: fake):
                raise RuntimeError('simulado')
        self.assertTrue(fake.released)

    def test_lbph_model_roundtrip_on_synthetic_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'model.yml'
            model = cv2.face.LBPHFaceRecognizer_create()
            sample = vision.prepare(self.gray, True)
            model.train([sample], np.array([0], dtype=np.int32))
            model.write(str(path))
            loaded = cv2.face.LBPHFaceRecognizer_create()
            loaded.read(str(path))
            label, distance = loaded.predict(sample)
            self.assertEqual(label, 0)
            self.assertLess(distance, 1)

    def test_cancelled_registration_releases_camera_without_saving(self):
        with tempfile.TemporaryDirectory() as d:
            stop = threading.Event()
            fake = FakeCamera(cancel=stop)
            path = Path(d) / 'model.yml'
            result = vision.run_camera('enroll', path, dict(camera=0, low_light=True, anti_photo=True),
                                       stop, threading.Event(), lambda *a: None,
                                       camera_factory=lambda *a: fake)
            self.assertIsNone(result[0])
            self.assertFalse(path.exists())
            self.assertTrue(fake.released)

    def test_read_error_releases_camera(self):
        with tempfile.TemporaryDirectory() as d:
            fake = FakeCamera(fail=True)
            with self.assertRaises(RuntimeError):
                vision.run_camera('enroll', Path(d)/'model.yml', dict(camera=0, low_light=True, anti_photo=True),
                                  threading.Event(), threading.Event(), lambda *a: None,
                                  camera_factory=lambda *a: fake)
            self.assertTrue(fake.released)


if __name__ == '__main__':
    unittest.main()
