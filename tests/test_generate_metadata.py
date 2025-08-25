import logging
import unittest
from unittest.mock import Mock, patch
from generate_metadata import (
    _get_uuid_by_record_id,
    _process_input_data,
)
from pymarc.record import Record as BibRecord
from fmrest.record import Record as FMRecord


class TestGenerateMetadata(unittest.TestCase):
    """Test the `generate_metadata` module."""

    def setUp(self):
        # Turn off logging for this test case, for all but CRITICAL
        # which we don't generally use.
        # Otherwise, test output is cluttered with log messages from
        # methods being tested.
        logging.disable(level=logging.CRITICAL)

        # Create sample config file
        self.sample_config = {
            "filemaker": {"user": "test_user", "password": "test_password"},
            "digital_data": {
                "user": "dd_user",
                "password": "dd_password",
                "url": "http://test.example.com",
            },
        }

        # Create sample input CSV data
        self.sample_input_data = [
            {"dl_record_id": "123", "Audio Track?": "no", "match_asset": ""},
            {"dl_record_id": "456", "Audio Track?": "yes", "match_asset": "789"},
        ]

        # Create sample BibRecord
        self.sample_bib_record = BibRecord()

        # Create sample FMRecord
        self.sample_fm_record = FMRecord([], [])

        # Create sample DigitalDataRecord
        self.sample_digital_data_record = {
            "inventory_number": "123",
            "uuid": "test-uuid-123",
        }

    @patch("generate_metadata.DigitalDataClient")
    def test_get_uuid_by_record_id_success(self, mock_dd_client):
        """Test successful UUID retrieval."""
        mock_record = {"uuid": "test-uuid-123"}
        mock_dd_client.return_value.get_record_by_id.return_value = mock_record

        # It doesn't matter what the record ID is, only that it's an int.
        # Mocking
        uuid = _get_uuid_by_record_id(123, mock_dd_client.return_value)
        self.assertEqual(uuid, "test-uuid-123")

    def test_process_input_data(self):
        """Test the `_process_input_data` function."""
        # Mock the clients
        alma_sru_client = Mock()
        filemaker_client = Mock()
        digital_data_client = Mock()

        # Mock the return values of the clients
        alma_sru_client.search_by_call_number.return_value = self.sample_bib_record
        filemaker_client.search_by_inventory_number.return_value = self.sample_fm_record
        digital_data_client.get_record_by_id.return_value = (
            self.sample_digital_data_record
        )

        # Use the mocked clients, which return the sample records defined in `setUp`.
        asset_data, track_data = _process_input_data(
            self.sample_input_data,
            alma_sru_client,
            filemaker_client,
            digital_data_client,
        )

        # These assertions are mostly placeholders.
        # TODO: figure out how best to test actual sample data.
        self.assertIsInstance(asset_data, list)
        self.assertIsInstance(track_data, list)
