import unittest
import io
import logging

from generate_metadata import (
    _validate_match_asset_relationships,
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

    def test_validate_match_asset_relationships_with_valid_match_asset(self):
        """Test that `_validate_match_asset_relationships`
        returns True when all match_asset relationships are valid.
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
            },  # valid match_asset relationship: both match_asset and inv no match target
        ]
        result = _validate_match_asset_relationships(test_records)
        self.assertTrue(result)

    def test_validate_match_asset_relationships_without_match_asset(self):
        """Test that `_validate_match_asset_relationships`
        returns True when there are no `match_asset` relationships.
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

        result = _validate_match_asset_relationships(test_records)
        self.assertTrue(result)

    def test_validate_match_asset_relationships_when_match_asset_is_missing(self):
        """Test that `_validate_match_asset_relationships`
        returns False and logs expected error
        when the targeted `match_asset` record is missing.
        """
        test_records = [
            {"uuid": "12345", "inventory_numbers": ["INV001"], "record_type": "asset"},
            {"uuid": "67890", "inventory_numbers": ["INV002"], "record_type": "asset"},
            {
                "uuid": "09876",
                "inventory_numbers": ["INV001"],
                "match_asset": "34567",  # this value is missing
                "record_type": "track",
            },
        ]

        result = _validate_match_asset_relationships(test_records)
        self.assertFalse(result)
        # There should be an error in logs about the missing target
        self.assertIn(
            "ERROR: Match asset 34567 for record 09876 not found in batch.",
            self.stream.getvalue(),
        )

    def test_validate_match_asset_relationships_when_inv_nos_do_not_match(self):
        """Test that `_validate_match_asset_relationships`
        returns False and logs expected error
        when the inventory numbers of the match_asset and target record do not match.
        """
        test_records = [
            {"uuid": "12345", "inventory_numbers": ["INV001"], "record_type": "asset"},
            {"uuid": "67890", "inventory_numbers": ["INV002"], "record_type": "asset"},
            {
                "uuid": "09876",
                "inventory_numbers": ["INV003"],  # inv no does not match the target
                "match_asset": "12345",
                "record_type": "track",
            },
        ]

        result = _validate_match_asset_relationships(test_records)
        self.assertFalse(result)
        self.assertIn(
            (
                "ERROR: Inventory numbers do not match for match_asset relationship "
                "track 09876: 'INV003', asset 12345: 'INV001'"
            ),
            self.stream.getvalue(),
        )
