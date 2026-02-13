import unittest

from generate_metadata import _set_record_type, _update_match_record_type


class TestGenerateMetadata(unittest.TestCase):
    """Test the `generate_metadata` module."""

    def test_set_record_type_with_match_asset(self):
        """Test that `_set_record_type` sets the `record_type` correctly
        when there is a `match_asset` relationship.
        """
        # Tuple of test records and expected results
        test_records = [
            {
                "uuid": "12345",
                "inventory_numbers": ["INV001"],
            },  # should be asset
            {
                "uuid": "67890",
                "inventory_numbers": ["INV002"],
            },  # should be asset
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "match_asset": "12345",
            },  # since inventory numbers match the target match_asset, should be track
        ]
        expected_results = [
            {
                "uuid": "12345",
                "inventory_numbers": ["INV001"],
                "record_type": "asset",
            },
            {
                "uuid": "67890",
                "inventory_numbers": ["INV002"],
                "record_type": "asset",
            },
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "match_asset": "12345",
                "record_type": "track",
            },
        ]

        result_records = _set_record_type(test_records)
        self.assertEqual(result_records, expected_results)

    def test_set_record_type_without_match_asset(self):
        """Test that `_set_record_type` sets the `record_type` correctly
        when there is no `match_asset` relationship.
        """
        test_records = [
            {
                "uuid": "12345",
                "inventory_numbers": ["INV001"],
            },  # should be asset
            {
                "uuid": "67890",
                "inventory_numbers": ["INV002"],
            },  # should be asset
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
            },  # since there is no match_asset relationship, should be asset
        ]
        expected_results = [
            {
                "uuid": "12345",
                "inventory_numbers": ["INV001"],
                "record_type": "asset",
            },
            {
                "uuid": "67890",
                "inventory_numbers": ["INV002"],
                "record_type": "asset",
            },
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "record_type": "asset",
            },
        ]

        result_records = _set_record_type(test_records)
        self.assertEqual(result_records, expected_results)

    def test_set_record_type_when_match_asset_is_missing(self):
        """Test that `_set_record_type` skips records
        when the `match_asset` cannot be found.
        """
        test_records = [
            {"uuid": "12345", "inventory_numbers": ["INV001"]},
            {"uuid": "67890", "inventory_numbers": ["INV002"]},
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "match_asset": "34567",
            },  # should be skipped, because target match_asset does not exist
        ]
        expected_results = [
            {"uuid": "12345", "inventory_numbers": ["INV001"], "record_type": "asset"},
            {"uuid": "67890", "inventory_numbers": ["INV002"], "record_type": "asset"},
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "match_asset": "34567",
            },  # there should be an error in logs about the missing match_asset
        ]

        result_records = _set_record_type(test_records)
        self.assertEqual(result_records, expected_results)

    def test_update_match_record_type_with_valid_match_asset(self):
        """Test that `_update_match_record_type` updates the `record_type` correctly
        when there is a valid `match_asset` relationship.
        """
        # Test cases comprised of (record with match, matched record, expected_result)
        test_cases = (
            (
                {
                    "uuid": "09876",
                    "inventory_numbers": ["INV001"],
                    "match_asset": "12345",
                },  # record with match
                {
                    "uuid": "12345",
                    "inventory_numbers": ["INV001"],
                },  # matched record
                {
                    "uuid": "09876",
                    "inventory_numbers": ["INV001"],
                    "match_asset": "12345",
                    "record_type": "track",
                },  # expected result
            ),  # where inventory numbers match the target match_asset, should be track
            (
                {
                    "uuid": "09876",
                    "inventory_numbers": ["INV002"],
                    "match_asset": "12345",
                },  # record with match
                {
                    "uuid": "12345",
                    "inventory_numbers": ["INV001"],
                },  # matched record
                {
                    "uuid": "09876",
                    "inventory_numbers": ["INV002"],
                    "match_asset": "12345",
                    "record_type": "asset",
                },  # expected result
            ),  # where inventory numbers do not match the target match_asset, should be asset
            (
                {
                    "uuid": "09876",
                    "inventory_numbers": [],
                    "match_asset": "12345",
                },  # record with match
                {
                    "uuid": "12345",
                    "inventory_numbers": ["INV001"],
                },  # matched record
                {
                    "uuid": "09876",
                    "inventory_numbers": [],
                    "match_asset": "12345",
                    "record_type": "asset",
                },  # expected result
            ),  # where either inventory number is missing, should be asset
        )

        for test_case in test_cases:
            with self.subTest(test_case=test_case):
                test_record, test_matched_record, expected_result = test_case
                result_record = _update_match_record_type(
                    test_record, test_matched_record
                )
                self.assertEqual(result_record, expected_result)
