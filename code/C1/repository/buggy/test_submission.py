"""Original deploy smoke test, intentionally weak coverage."""
import unittest
import service


class SmokeTest(unittest.TestCase):
    def test_accepts_regular_envelope(self):
        service.validate_batch("A", "request", [{"tenant": "A", "id": "p", "kind": "post", "entries": [["a", 1], ["b", -1]]}])


if __name__ == "__main__":
    unittest.main()
