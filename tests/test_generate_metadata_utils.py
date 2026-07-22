import unittest

from utils.generate_metadata_utils import validate_match_asset_relationships


class TestGenerateMetadata(unittest.TestCase):
    """Tests for `utils.generate_metadata_utils`."""

    def test_validate_match_asset_relationships_with_valid_match_asset(self):
        """Test that `validate_match_asset_relationships`
        returns empty list when all match_asset relationships are valid.
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
        result = validate_match_asset_relationships(test_records)
        # When all match_asset relationships are valid, result should be empty list
        self.assertEqual(result, [])

    def test_validate_match_asset_relationships_without_match_asset(self):
        """Test that `validate_match_asset_relationships`
        returns empty list when there are no `match_asset` relationships.
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
        result = validate_match_asset_relationships(test_records)
        # When no match_asset relationships, result should be empty list
        self.assertEqual(result, [])

    def test_validate_match_asset_relationships_when_match_asset_is_missing(self):
        """Test that `validate_match_asset_relationships`
        returns list of validation problems
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

        result = validate_match_asset_relationships(test_records)
        # Result should contain one message, since there is one missing match_asset relationship
        self.assertEqual(
            result,
            ["Match asset 34567 for record 09876 not found in batch."],
        )

    def test_validate_match_asset_relationships_when_inv_nos_do_not_match(self):
        """Test that `validate_match_asset_relationships`
        returns list of validation problems
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

        result = validate_match_asset_relationships(test_records)
        # Result should contain one message, since there is one inv no mismatch
        self.assertEqual(
            result,
            [
                "Inventory numbers do not match for match_asset relationship: "
                "track 09876: 'INV003', asset 12345: 'INV001'"
            ],
        )

    def test_validate_match_asset_relationships_with_check_inventory_numbers_false(
        self,
    ):
        """Test that `validate_match_asset_relationships`
        returns True when `check_inventory_numbers` is False,
        even if the inventory numbers of the match_asset and target record do not match.
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

        result = validate_match_asset_relationships(
            test_records, check_inventory_numbers=False
        )
        # Result should be empty list, since inv no check is disabled
        self.assertEqual(result, [])
