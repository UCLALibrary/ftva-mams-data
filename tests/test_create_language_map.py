import unittest
from create_language_map import _get_language_value


class TestCreateLanguageMap(unittest.TestCase):
    def setUp(self):
        # Copied from real data. This has both a string value (code)
        # and a dict value (name), supporting tests of both options
        # in _get_language_value().
        self.language_data = {
            "uri": "info:lc/vocabulary/languages/abk",
            "name": {"@authorized": "yes", "#text": "Abkhaz"},
            "code": "abk",
        }

    def test_language_value_from_string(self):
        value = _get_language_value(self.language_data, element_name="code")
        self.assertEqual(value, "abk")

    def test_language_value_from_dict(self):
        value = _get_language_value(self.language_data, element_name="name")
        self.assertEqual(value, "Abkhaz")

    def test_language_value_invalid_element_name(self):
        with self.assertRaises(ValueError):
            _ = _get_language_value(self.language_data, element_name="invalid")
