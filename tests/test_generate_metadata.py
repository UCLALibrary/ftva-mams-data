import unittest
import io
import logging

from generate_metadata import (
    _set_record_type_and_match_asset,
    _validate_match_asset_relationships,
    _compare_inventory_numbers,
    logger,
)


class TestGenerateMetadata(unittest.TestCase):
    """Test the `generate_metadata` module."""

    def setUp(self):
        # The logger used in these tests is imported from `generate_metadata.py`,
        # so this setUp method clears existing file and console handlers,
        # then sets up a new test handler that captures the messages emitted in `generate_metadata`
        # to an IO stream, which can then be used in tests, without log files or console output.
        for handler in logger.handlers:
            handler.close()
            logger.removeHandler(handler)

        stream = io.StringIO()
        test_handler = logging.StreamHandler(stream)
        formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        test_handler.setFormatter(formatter)
        logger.addHandler(test_handler)

        self.logger = logger
        self.stream = stream

    def tearDown(self):
        # Reset the test handler after each test, to avoid multiple streams being created.
        for handler in self.logger.handlers:
            handler.close()
            self.logger.removeHandler(handler)

    def test_set_record_type_and_match_asset(self):
        """Test that `_set_record_type_and_match_asset`
        sets `record_type` and `match_asset` correctly."""
        test_digital_data_records = [
            {
                "uuid": "12345",
                "inventory_numbers": ["INV001"],
            },
            {
                "uuid": "67890",
                "inventory_numbers": ["INV002"],
                "incoming_relationships": [
                    {
                        "relationship_type": "isTrackOf",
                        "source_uuid": "12345",
                    }
                ],
            },  # track relationship indicated in DD record targeting asset 12345
        ]
        expected_results = [
            {
                "uuid": "12345",
                "inventory_numbers": ["INV001"],
                "record_type": "asset",
            },  # this output should be an asset
            {
                "uuid": "67890",
                "inventory_numbers": ["INV002"],
                "record_type": "track",
                "match_asset": "12345",
            },  # this output should be a track, with match_asset set to UUID of the asset
        ]

        # Zip together the two lists to get tuples of (dd_record, expected_result)
        for dd_record, expected_result in zip(
            test_digital_data_records, expected_results
        ):
            with self.subTest(dd_record=dd_record, expected_result=expected_result):
                metadata_record = _set_record_type_and_match_asset(
                    dd_record, expected_result
                )
                self.assertEqual(metadata_record, expected_result)

    def test_validate_match_asset_relationships_with_valid_match_asset(self):
        """Test that `_validate_match_asset_relationships`
        leaves the `record_type` and `match_asset` values unchanged
        when the `match_asset` relationship is valid.
        """
        test_records = [
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
            },  # valid match_asset relationship, so should be unchanged
        ]

        result_records = _validate_match_asset_relationships(test_records)
        self.assertEqual(result_records, test_records)

    def test_validate_match_asset_relationships_without_match_asset(self):
        """Test that `_validate_match_asset_relationships`
        sets the `record_type` correctly when there is no `match_asset` relationship.
        """
        test_records = [
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

        result_records = _validate_match_asset_relationships(test_records)
        # All test records should remain `assets`, since there is no match_asset relationship.
        self.assertEqual(result_records, test_records)

    def test_validate_match_asset_relationships_when_match_asset_is_missing(self):
        """Test that `_validate_match_asset_relationships` logs an error
        when the targeted `match_asset` record is not in the batch.
        """
        test_records = [
            {"uuid": "12345", "inventory_numbers": ["INV001"], "record_type": "asset"},
            {"uuid": "67890", "inventory_numbers": ["INV002"], "record_type": "asset"},
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "match_asset": "34567",  # missing from "batch", i.e. `test_records`
                "record_type": "track",
            },  # there should be an error in logs about the missing match_asset
        ]

        result_records = _validate_match_asset_relationships(test_records)
        # Test records should remain unchanged
        self.assertEqual(result_records, test_records)
        # `_validate_match_asset_relationships` should log an error about the missing match_asset.
        # Check for it here in the test IO stream being used as the test log handler.
        self.assertIn(
            "ERROR: Match asset 34567 for record 09876 not found in batch.",
            self.stream.getvalue(),
        )

    def test_compare_inventory_numbers_with_valid_match_asset(self):
        """Test that `_compare_inventory_numbers` updates the `record_type` correctly
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
                result_record = _compare_inventory_numbers(
                    test_record, test_matched_record
                )
                self.assertEqual(result_record, expected_result)
