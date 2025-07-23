import logging
import unittest
from pymarc import Field, Indicators, Record, Subfield
from generate_metadata import (
    _get_language_name,
    _get_language_map,
    _get_main_title_from_bib,
    _get_alternative_titles_from_bib,
    _get_series_title_from_bib,
    _get_episode_title_from_bib,
    _get_title_info,
    _get_asset_type,
    _get_file_name,
)


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

    def test_get_main_title_minimal_record(self):
        record = self.minimal_bib_record
        main_title = _get_main_title_from_bib(record)
        self.assertEqual(main_title, "F245a")

    def test_get_alternative_titles_valid_indicators(self):
        record = self.minimal_bib_record

        # Valid indicators are 0 or 2 or 3 followed by whitespace
        field_246_1 = Field(
            tag="246",
            indicators=Indicators("0", " "),
            subfields=[
                Subfield(code="a", value="foo"),
            ],
        )
        field_246_2 = Field(
            tag="246",
            indicators=Indicators("2", " "),
            subfields=[
                Subfield(code="a", value="bar"),
            ],
        )
        field_246_3 = Field(
            tag="246",
            indicators=Indicators("3", " "),
            subfields=[
                Subfield(code="a", value="baz"),
            ],
        )
        record.add_field(field_246_1)
        record.add_field(field_246_2)
        record.add_field(field_246_3)
        alternative_titles = _get_alternative_titles_from_bib(record)
        self.assertListEqual(alternative_titles, ["foo", "bar", "baz"])

    def test_get_alternative_titles_invalid_indicators(self):
        record = self.minimal_bib_record

        # Trying different invalid indicator combos
        field_246_1 = Field(
            tag="246",
            indicators=Indicators("0", "1"),
            subfields=[
                Subfield(code="a", value="foo"),
            ],
        )
        field_246_2 = Field(
            tag="246",
            indicators=Indicators("5", " "),
            subfields=[
                Subfield(code="a", value="bar"),
            ],
        )
        field_246_3 = Field(
            tag="246",
            indicators=Indicators(" ", " "),
            subfields=[
                Subfield(code="a", value="baz"),
            ],
        )
        record.add_field(field_246_1)
        record.add_field(field_246_2)
        record.add_field(field_246_3)
        alternative_titles = _get_alternative_titles_from_bib(record)
        self.assertListEqual(alternative_titles, [])

    def test_get_series_title(self):
        record = self.minimal_bib_record
        field_245 = record.get("245")

        main_title = record.get_fields("245")[0].get_subfields("a")[0]
        series_subfield_codes = ["n", "p", "g"]  # g should result in ""
        for code in series_subfield_codes:
            with self.subTest(code=code):
                if field_245:  # this is just to avoid linting errors
                    field_245.add_subfield(code=code, value=f"F245{code}")
                    series_title = _get_series_title_from_bib(record, main_title)
                    # If 245 $n or 245 $p exists on record,
                    # series title should be main title (245 $a),
                    # else it should be an empty string.
                    if code in ["n", "p"]:  #
                        self.assertEqual(series_title, main_title)
                    else:
                        self.assertEqual(series_title, "")
                    field_245.delete_subfield(code=code)

    def test_get_episode_title(self):
        record = self.minimal_bib_record
        field_245 = record.get("245")
        if field_245:  # to avoid linting error
            field_245.add_subfield(code="n", value="Episode 001")
            field_245.add_subfield(
                code="p",
                value="Pilot--unedited footage. Pam Jennings interviews Marlon Riggs",
            )

        field_246 = Field(tag="246", subfields=[Subfield(code="n", value="F246n")])
        record.add_field(field_246)

        episode_title = _get_episode_title_from_bib(record)

        # Expected output comes from specs.
        # Specs indicate that 245 $p should come first and be joined with 245 $n and 246 $n
        # if they exist, using ". " as delimiter
        expected_output = (
            "Pilot--unedited footage. Pam Jennings interviews Marlon Riggs. "
            "Episode 001. "
            "F246n"
        )
        self.assertEqual(episode_title, expected_output)

    def test_get_title_info(self):
        # Testing the main coordinating function
        # that calls all the smaller title-specific methods.

        record = self.minimal_bib_record
        field_245 = record.get("245")
        if field_245:  # to avoid linting error
            field_245.add_subfield(code="n", value="F245n")
            field_245.add_subfield(code="p", value="F245p")

        field_246_1 = Field(
            tag="246",
            indicators=Indicators("0", " "),  # indicators are valid
            subfields=[
                Subfield(code="a", value="F246a_1"),
                Subfield(code="n", value="F246n_1"),
            ],
        )
        field_246_2 = Field(
            tag="246",
            indicators=Indicators("2", " "),  # indicators are valid
            subfields=[
                Subfield(code="a", value="F246a_2"),
                Subfield(code="n", value="F246n_2"),
            ],
        )
        record.add_field(field_246_1, field_246_2)

        expected_output = {
            "title": "F245a F245p. F245n. F246n_1. F246n_2",
            "series_title": "F245a",  # main title from minimal record
            "alternative_titles": ["F246a_1", "F246a_2"],
            "episode_title": "F245p. F245n. F246n_1. F246n_2",
        }
        titles = _get_title_info(record)
        self.assertEqual(titles, expected_output)

    def test_get_file_name_valid_extension(self):
        item = {"file_name": "filename.wav"}
        file_name = _get_file_name(item)
        self.assertEqual(file_name, "filename")

    def test_get_file_name_invalid_extension(self):
        item = {"file_name": "filename.XYZ"}
        file_name = _get_file_name(item)
        self.assertEqual(file_name, "filename.XYZ")

    def test_get_file_name_multiple_extension(self):
        item = {"file_name": "filename.something.wav"}
        file_name = _get_file_name(item)
        self.assertEqual(file_name, "filename.something")

    def test_get_file_name_no_extension(self):
        item = {"file_name": "filename"}
        file_name = _get_file_name(item)
        self.assertEqual(file_name, "filename")
