import tempfile
import unittest
from pathlib import Path
import numpy as np
import vision

class EmbeddingTests(unittest.TestCase):
    def test_dpapi_roundtrip_never_writes_plaintext_vectors(self):
        embeddings = [np.arange(1, 129, dtype=np.float32)]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'face.dat'
            vision.save_embeddings(path, embeddings)
            payload = path.read_bytes()
            self.assertNotIn(b'1.0, 2.0', payload)
            restored = vision.load_embeddings(path)
            self.assertEqual(len(restored), 1)
            np.testing.assert_allclose(restored[0], embeddings[0], rtol=1e-6)

    def test_matching_uses_multiple_samples_and_rejects_different_identity(self):
        known = [np.array([1., 0.]), np.array([0.8, 0.6])]
        self.assertTrue(vision.matches_identity(np.array([0.8, 0.6]), known))
        self.assertFalse(vision.matches_identity(np.array([-1., 0.]), known))

    def test_zero_vector_and_nonfinite_embeddings_rejected(self):
        for vector in (np.zeros(128), np.full(128, np.nan)):
            with self.assertRaises(ValueError):
                vision.matches_identity(vector, [np.ones(128)])

    def test_unusable_dark_frame_rejected_before_detection(self):
        class Detector:
            def detect(self, frame):
                raise AssertionError('Dark frame reached detector')
        face, state = vision.extract_face(np.zeros((240, 320, 3), np.uint8), Detector(), True)
        self.assertIsNone(face)
        self.assertEqual(state, 'unknown')

    def test_missing_and_multiple_faces_are_rejected(self):
        class Detector:
            def __init__(self, faces): self.faces = faces
            def setInputSize(self, size): pass
            def detect(self, frame): return 1, self.faces
        frame = np.tile(np.arange(160, dtype=np.uint8), (160, 1))
        frame = np.repeat(frame[:, :, None], 3, axis=2)
        for faces in (None, np.ones((2, 15), dtype=np.float32)):
            face, state = vision.extract_face(frame, Detector(faces), True)
            self.assertIsNone(face)
            self.assertEqual(state, 'unknown')

    def test_enrollment_keeps_both_light_modes_without_plaintext(self):
        normal = [np.arange(1, 129, dtype=np.float32)]
        enhanced = [np.arange(129, 257, dtype=np.float32)]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'face.dat'
            vision.save_embeddings(path, normal, enhanced)
            np.testing.assert_allclose(vision.load_embeddings(path, low_light=False)[0], normal[0])
            np.testing.assert_allclose(vision.load_embeddings(path, low_light=True)[0], enhanced[0])
            self.assertNotIn(b'129.0', path.read_bytes())
