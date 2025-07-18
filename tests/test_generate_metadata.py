import logging
import unittest
from pymarc import Field, Indicators, Record, Subfield
from generate_metadata import _get_language_name, _get_language_map, _get_asset_type


class TestGenerateMetadata(unittest.TestCase):
    def setUp(self):
        # Turn off logging for this test case, for all but CRITICAL
        # which we don't generally use.
        # Otherwise, test output is cluttered with log messages from
        # methods being tested.
        logging.disable(level=logging.CRITICAL)

        self.language_map = _get_language_map("language_map.json")
        self.minimal_bib_record = self._get_minimal_bib_record()

    def _get_minimal_bib_record(self) -> Record:
        """Create a valid but minimal bib record with just 001 and 245 $a.
        This will be used as the base record, then copied & modified
        for other tests as needed.

        :return record: Minimal bib record with just 001 and 245 fields.
        """
        field_001 = Field(tag="001", data="12345")
        field_245 = Field(
            tag="245",
            indicators=Indicators("0", "0"),
            subfields=[Subfield(code="a", value="F245a")],
        )
        record = Record()
        record.add_field(field_001)
        record.add_field(field_245)
        return record

    def _get_bib_record_bad_008(self) -> Record:
        """Create a bib record with an invalid 008 field,
        with bad data and incorrect length.

        :return record: Minimal bib record with a bad 008 field.

        """
        bad_field_008 = Field(tag="008", data="xxxxxxxxxxxxxxxx")
        record = self.minimal_bib_record
        record.add_field(bad_field_008)
        return record

    def test_get_language_name_no_008(self):
        # The minimal record has no 008 field.
        record = self.minimal_bib_record
        language_name = _get_language_name(record, self.language_map)
        self.assertEqual(language_name, "")

    def test_get_language_name_bad_008(self):
        record = self._get_bib_record_bad_008()
        language_name = _get_language_name(record, self.language_map)
        self.assertEqual(language_name, "")

    def test_get_language_name_invalid_code(self):
        # The minimal record has no 008 field; add one with an invalid
        # language code in positions 35-37.  Other data in the 008
        # does not matter for this, so use spaces.

        # A bib 008 field must have 40 characters.
        spaces = " " * 40
        # Set positions 35-37 to an invalid language code (not in the language map).
        field_008_data = spaces[:35] + "BAD" + spaces[38:]
        record = self.minimal_bib_record
        # Add the bad 008 field
        record.add_field(Field(tag="008", data=field_008_data))
        language_name = _get_language_name(record, self.language_map)
        self.assertEqual(language_name, "")

    def test_get_language_name_valid_code(self):
        # The minimal record has no 008 field; add one with a valid
        # language code in positions 35-37.  Other data in the 008
        # does not matter for this, so use spaces.

        # A bib 008 field must have 40 characters.
        spaces = " " * 40
        # Set positions 35-37 to a valid language code (in the language map).
        field_008_data = spaces[:35] + "fre" + spaces[38:]
        record = self.minimal_bib_record
        # Add the good 008 field
        record.add_field(Field(tag="008", data=field_008_data))
        language_name = _get_language_name(record, self.language_map)
        self.assertEqual(language_name, "French")

    def test_get_asset_type_raw(self):
        item = {"file_name": "example_raw_file.mov"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "Raw")

    def test_get_asset_type_intermediate(self):
        item = {"file_name": "example_file_mti.mov"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "Intermediate")

    def test_get_asset_type_final(self):
        item = {"file_name": "example_file_final.mov"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "Final Version")

    def test_get_asset_type_derivative(self):
        item = {"file_name": "example_file_finals_finals.mov"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "Derivative")

    def test_get_asset_type_unknown(self):
        item = {"file_name": "example_file.mov"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "")

    def test_get_asset_type_dpx_intermediate(self):
        item = {"folder_name": "example_folder_MTI", "file_type": "DPX"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "Intermediate")

    def test_get_asset_type_dpx_raw(self):
        item = {"folder_name": "example_folder", "file_type": "DPX"}
        asset_type = _get_asset_type(item)
        self.assertEqual(asset_type, "Raw")
