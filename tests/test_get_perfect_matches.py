import unittest
from get_perfect_matches import _get_singletons


class TestSingletons(unittest.TestCase):
    def setUp(self):
        self.sample_data: list[dict] = [
            {"inventory_number": "123", "other_fields": "record 1"},
            {"inventory_number": "456", "other_fields": "record 2"},
            {"inventory_number": "789", "other_fields": "record 3"},
            {"inventory_number": "123", "other_fields": "dup of record 1"},
        ]

    def test_unique_values_are_returned(self):
        singletons = _get_singletons(self.sample_data)
        self.assertEqual(len(singletons), 2)
        # Make sure the unique keys are all present.
        for inventory_number in ["456", "789"]:
            with self.subTest(inventory_number=inventory_number):
                self.assertIn(inventory_number, singletons)

    def test_duplicate_values_are_not_returned(self):
        singletons = _get_singletons(self.sample_data)
        # Make sure the duplicate key is not present.
        self.assertNotIn("123", singletons)
