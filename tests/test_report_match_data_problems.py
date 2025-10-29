import unittest
from pymarc import Record, Field, Indicators, Subfield
from report_match_data_problems import (
    has_no_008,
    invalid_language,
    no_26x_date,
    lacks_attribution_phrase,
)


class TestReportMatchDataProblems(unittest.TestCase):
    def setUp(self):
        self.alma_data = self._get_alma_data()
        self.filemaker_data = self._get_filemaker_data()

    def _get_alma_data(self) -> dict[str, list]:
        alma_data = {
            "INV_NO_02": [  # Multiple Alma records
                {"recordId": "A1", "marc_record": self._create_marc_record("Title A1")},
                {"recordId": "A2", "marc_record": self._create_marc_record("Title A2")},
            ],
            "INV_NO_06": [  # Multiple Alma records
                {"recordId": "A3", "marc_record": self._create_marc_record("Title A3")},
                {"recordId": "A4", "marc_record": self._create_marc_record("Title A4")},
            ],
            "INV_NO_07": [  # Multiple Alma records
                {"recordId": "A5", "marc_record": self._create_marc_record("Title A5")},
                {"recordId": "A6", "marc_record": self._create_marc_record("Title A6")},
            ],
        }
        return alma_data

    def _get_filemaker_data(self) -> dict[str, list]:
        filemaker_data = {
            "INV_NO_03": [  # Multiple FileMaker records
                {"recordId": "F1", "title": "Title F1"},
                {"recordId": "F2", "title": "Title F2"},
            ],
            "INV_NO_05": [  # Multiple FileMaker records
                {"recordId": "F3", "title": "Title F3"},
                {"recordId": "F4", "title": "Title F4"},
            ],
            "INV_NO_07": [  # Multiple FileMaker records
                {"recordId": "F5", "title": "Title F5"},
                {"recordId": "F6", "title": "Title F6"},
            ],
        }

        return filemaker_data

    def _create_marc_record(self, title: str):
        record = Record()
        record.add_field(
            Field(
                tag="245",
                indicators=Indicators("1", "0"),
                subfields=[Subfield("a", title)],
            )
        )
        return record

    def test_has_no_008(self):
        record_with_008 = Record()
        record_with_008.add_field(Field(tag="008", data="Some data"))

        record_without_008 = Record()

        self.assertFalse(has_no_008(record_with_008))
        self.assertTrue(has_no_008(record_without_008))

    def test_invalid_language(self):
        valid_language_codes = set(["eng", "fre", "spa", "ger"])  # Example valid codes
        record_with_valid_lang = Record()
        record_with_valid_lang.add_field(
            Field(
                tag="008", data="210702s1946    xxu               mleng d"
            )  # Valid lang code "eng"
        )

        record_with_invalid_lang = Record()
        record_with_invalid_lang.add_field(
            Field(
                tag="008", data="210702s1946    xxu               mlabc d"
            )  # Invalid lang code "abc"
        )
        record_with_no_lang = Record()
        record_with_no_lang.add_field(
            Field(
                tag="008", data="210702s1946    xxu                      d"
            )  # No lang code
        )

        self.assertFalse(invalid_language(record_with_valid_lang, valid_language_codes))
        self.assertTrue(
            invalid_language(record_with_invalid_lang, valid_language_codes) == "abc"
        )
        self.assertTrue(
            invalid_language(record_with_no_lang, valid_language_codes) == "BLANK"
        )

    def test_no_26x_date(self):
        record_with_260 = Record()
        record_with_260.add_field(
            Field(
                tag="260",
                indicators=Indicators(" ", " "),
                subfields=[Subfield("c", "10/14/1946")],
            )
        )

        record_with_264 = Record()
        record_with_264.add_field(
            Field(
                tag="264",
                indicators=Indicators(" ", "1"),
                subfields=[Subfield("c", "1950")],
            )
        )
        record_without_26x = Record()

        self.assertFalse(no_26x_date(record_with_260))
        self.assertFalse(no_26x_date(record_with_264))
        self.assertTrue(no_26x_date(record_without_26x))

    def test_lacks_attribution_phrase(self):
        record_with_directed = Record()
        record_with_directed.add_field(
            Field(
                tag="245",
                indicators=Indicators("1", "0"),
                subfields=[Subfield("c", "Directed by John Doe")],
            )
        )

        record_without_phrase = Record()
        record_without_phrase.add_field(
            Field(
                tag="245",
                indicators=Indicators("1", "0"),
                subfields=[Subfield("c", "Some other text")],
            )
        )

        record_with_a_film_by = Record()
        record_with_a_film_by.add_field(
            Field(
                tag="245",
                indicators=Indicators("1", "0"),
                subfields=[Subfield("c", "A film by Jane Smith")],
            )
        )
        self.assertFalse(lacks_attribution_phrase(record_with_directed))
        self.assertTrue(lacks_attribution_phrase(record_without_phrase))
        self.assertFalse(lacks_attribution_phrase(record_with_a_film_by))
