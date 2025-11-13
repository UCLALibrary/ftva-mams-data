import unittest
from pymarc import Record, Field, Indicators, Subfield
from report_match_data_problems import (
    has_no_008,
    invalid_language,
    no_26x_date,
    lacks_attribution_phrase,
    get_alma_title,
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
                subfields=[
                    Subfield("a", title),
                    Subfield("b", "Remainder of title"),
                    Subfield("n", "Number of part"),
                    Subfield("p", "Name of part"),
                ],
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

    def test_get_alma_title_with_leading_articles(self):
        records = []
        articles = ["The ", "A ", "An "]

        for article in articles:
            record = Record()
            record.add_field(
                Field(
                    tag="245",
                    # Indicator 2 is offset of leading article
                    indicators=Indicators("1", str(len(article))),
                    subfields=[
                        Subfield("a", f"{article}main title"),
                        Subfield("b", "Remainder of title"),
                        Subfield("n", "Number of part"),
                        Subfield("p", "Name of part"),
                    ],
                )
            )
            records.append((record, article))

        for record, article in records:
            with self.subTest(record=record):
                title, check_245_indicator_2 = get_alma_title(record)
                # Leading article should be moved to end of $a
                expected_title = (
                    f"main title, {article.strip()}. Remainder of title. "
                    "Number of part. Name of part"
                )
                self.assertEqual(title, expected_title)
                self.assertFalse(check_245_indicator_2)

    def test_get_alma_title_without_leading_article(self):
        record = Record()
        record.add_field(
            Field(
                tag="245",
                indicators=Indicators("1", "0"),
                subfields=[
                    Subfield("a", "Main title"),
                    Subfield("b", "Remainder of title"),
                    Subfield("n", "Number of part"),
                    Subfield("p", "Name of part"),
                ],
            )
        )
        title, check_245_indicator_2 = get_alma_title(record)
        expected_title = "Main title. Remainder of title. Number of part. Name of part"
        self.assertEqual(title, expected_title)
        self.assertFalse(check_245_indicator_2)

    def test_get_alma_title_with_bad_indicators(self):
        # Note 0 can be coerced to an integer, but is not a possible article length
        bad_indicators = ["X", "_", "", "0"]
        records = []
        for bad_indicator in bad_indicators:
            record = Record()
            record.add_field(
                Field(
                    tag="245",
                    indicators=Indicators("1", bad_indicator),
                    subfields=[
                        Subfield("a", "The main title"),  # Has leading English article
                        Subfield("b", "Remainder of title"),
                        Subfield("n", "Number of part"),
                        Subfield("p", "Name of part"),
                    ],
                )
            )
            records.append(record)
        for record in records:
            with self.subTest(record=record):
                title, check_245_indicator_2 = get_alma_title(record)
                # If indicator is bad, leading English articles should still be moved
                expected_title = (
                    "main title, The. Remainder of title. Number of part. Name of part"
                )
                self.assertEqual(title, expected_title)
                self.assertTrue(check_245_indicator_2)

    def test_get_alma_title_indicator_article_mismatch(self):
        record = Record()
        record.add_field(
            Field(
                tag="245",
                indicators=Indicators(
                    "1", "2"
                ),  # indicator 2 is wrong length for article
                subfields=[
                    Subfield("a", "The main title"),
                    Subfield("b", "Remainder of title"),
                    Subfield("n", "Number of part"),
                    Subfield("p", "Name of part"),
                ],
            )
        )
        title, check_245_indicator_2 = get_alma_title(record)
        # Leading article should still be moved to end,
        # despite the indicator mismatch.
        expected_title = (
            "main title, The. Remainder of title. Number of part. Name of part"
        )
        self.assertEqual(title, expected_title)
        self.assertTrue(check_245_indicator_2)

    def test_get_alma_title_non_english_article(self):
        record = Record()
        record.add_field(
            Field(
                tag="245",
                indicators=Indicators("1", "3"),
                subfields=[
                    Subfield("a", "La main title"),  # Non-English article
                    Subfield("b", "Remainder of title"),
                    Subfield("n", "Number of part"),
                    Subfield("p", "Name of part"),
                ],
            )
        )
        title, check_245_indicator_2 = get_alma_title(record)
        # So long as it's valid, the non-filing chars should be honored,
        # even if it's not an English article
        expected_title = (
            "main title, La. Remainder of title. Number of part. Name of part"
        )
        self.assertEqual(title, expected_title)
        self.assertFalse(check_245_indicator_2)
