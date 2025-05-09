import unittest
from report_inventory_number_matches import (
    id_dict,
    InventoryNumberData,
    _get_one_to_many_matches,
    _get_many_to_many_matches,
)


class TestInventoryNumberMatching(unittest.TestCase):
    def setUp(self):
        self.alma_data = self._get_alma_data()
        self.filemaker_data = self._get_filemaker_data()
        # self.google_data = self._get_google_data()

    def _get_alma_data(self) -> InventoryNumberData:
        alma_identifiers: id_dict = {
            # Used for one_to_many matches
            "INV_NO_01": ["A1"],
            "INV_NO_02": ["A2", "A3"],
            "INV_NO_05": ["A4"],
            "INV_NO_06": ["A5", "A6"],
            "INV_NO_07": ["A7", "A8"],
            # Used for many_to_many matches
            "INV_NO_11": ["A11"],
            "INV_NO_13": ["A12", "A13"],
        }
        alma_data = InventoryNumberData(
            source_system="Alma",
            identifier_label="Holdings IDs",
            identifiers=alma_identifiers,
        )
        return alma_data

    def _get_filemaker_data(self) -> InventoryNumberData:
        filemaker_identifiers: id_dict = {
            # Used for one_to_many matches
            "INV_NO_03": ["F1", "F2"],
            "INV_NO_04": ["F3"],
            "INV_NO_05": ["F4", "F5"],
            "INV_NO_06": ["F6"],
            "INV_NO_07": ["F7", "F8"],
            # Used for many_to_many matches
            "INV_NO_12": ["F12"],
        }
        filemaker_data = InventoryNumberData(
            source_system="Filemaker",
            identifier_label="Record IDs",
            identifiers=filemaker_identifiers,
        )
        return filemaker_data

    # def _get_google_data(self) -> set[str]:
    #     google_data = {"INV_NO_01", "INV_NO_02", "INV_NO_03|INV_NO_04"}
    #     return google_data

    def test_multiple_fm_no_alma(self):
        # Test case from report_single_values
        matches = _get_one_to_many_matches(
            "INV_NO_03", self.alma_data, self.filemaker_data
        )
        self.assertEqual(matches.alma_count, 0)
        self.assertGreater(matches.filemaker_count, 1)

    def test_multiple_alma_no_fm(self):
        # Test case from report_single_values
        matches = _get_one_to_many_matches(
            "INV_NO_02", self.alma_data, self.filemaker_data
        )
        self.assertGreater(matches.alma_count, 1)
        self.assertEqual(matches.filemaker_count, 0)

    def test_multiple_fm_one_alma(self):
        # Test case from report_single_values
        matches = _get_one_to_many_matches(
            "INV_NO_05", self.alma_data, self.filemaker_data
        )
        self.assertEqual(matches.alma_count, 1)
        self.assertGreater(matches.filemaker_count, 1)

    def test_multiple_alma_one_fm(self):
        # Test case from report_single_values
        matches = _get_one_to_many_matches(
            "INV_NO_06", self.alma_data, self.filemaker_data
        )
        self.assertGreater(matches.alma_count, 1)
        self.assertEqual(matches.filemaker_count, 1)

    def test_multiple_fm_multiple_alma(self):
        # Test case from report_single_values
        matches = _get_one_to_many_matches(
            "INV_NO_07", self.alma_data, self.filemaker_data
        )
        self.assertGreater(matches.alma_count, 1)
        self.assertGreater(matches.filemaker_count, 1)

    def test_no_fm_no_alma(self):
        # Test case from report_single_values
        matches = _get_one_to_many_matches(
            "INV_NO_99", self.alma_data, self.filemaker_data
        )
        self.assertEqual(matches.alma_count, 0)
        self.assertEqual(matches.filemaker_count, 0)

    def test_each_to_one_fm_or_alma(self):
        # Test case from report_multiple_values
        compound_value = "INV_NO_11|INV_NO_12"
        matches = _get_many_to_many_matches(
            compound_value, self.alma_data, self.filemaker_data
        )
        # Each match in matches must have total_count == 1
        self.assertTrue(all([match.total_count == 1 for match in matches]))

    def test_at_least_one_to_mult_fm_or_alma(self):
        # Test case from report_multiple_values
        compound_value = "INV_NO_13|INV_NO_14"
        matches = _get_many_to_many_matches(
            compound_value, self.alma_data, self.filemaker_data
        )
        # Does at least one inventory number match multiple records (in FM and/or Alma)?
        # For this test case, INV_NO_13 has 2 records for Alma (none for FM);
        # INV_NO_14 has no records for Alma or FM.
        self.assertTrue(
            any(
                [
                    (match.alma_count > 1 or match.filemaker_count > 1)
                    for match in matches
                ]
            )
        )
