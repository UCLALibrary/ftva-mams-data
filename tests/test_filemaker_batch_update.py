import unittest
from filemaker_batch_update import _apply_transformers


class TestFilemakerBatchUpdate(unittest.TestCase):
    """Tests for the `filemaker_batch_update` script."""

    def setUp(self):
        # Test values derived from standardization rules provided by FTVA staff
        # Organized as (input, expected output) tuples
        self.test_production_type_values = [
            ("Newsreel", "NEWSREELS"),
            ("TITLES, BKGD, OUTS\r ", "TITLES, BKGD, Overlays"),
            ("Made for TV Movies", "MADE FOR TV MOVIE"),
            ("MADE-FOR-TV", "MADE FOR TV MOVIE"),
            ("Silent Films", "SILENT FILM"),
            ("SILENT FILMS", "SILENT FILM"),
            ("SF \rSHORT", "SHORT"),
            ("SF \rNEWSREELS", "NEWSREELS"),
            ("SF \rTITLES, BKGD, OUTS", "TITLES, BKGD, Overlays"),
            ("SF \rUNEDITED FOOTAGE", "UNEDITED FOOTAGE"),
            ("SF \rTRAILERS AND PROMOS", "TRAILERS AND PROMOS"),
            ("SF \rHOME MOVIES", "HOME MOVIES"),
            ("SF \rSHORT\rCOMPILATION", "SHORT\rCOMPILATION"),
            (
                "SF \rTITLES, BKGD, OUTS\rCARTOONS",
                "TITLES, BKGD, Overlays\rCARTOONS",
            ),
            (
                "SF \rUNEDITED FOOTAGE\rTRAILERS AND PROMOS",
                "UNEDITED FOOTAGE\rTRAILERS AND PROMOS",
            ),
            ("SE \rSHORT", "SHORT"),
            (
                "FULL SILENT APERTURE 1.33:1\rSHORT\rANIMATION\rSPECIALS",
                "SHORT\rANIMATION\rSPECIALS",
            ),
            (
                "B&W\rTRIMS & OUTS",
                "B&W\rTrims and Outs",  # special case: "Trims and Outs" keeps casing
            ),  # & should be replaced with "and", except for special cases such as B&W
            (
                "SHORT SHORT\rTRIMS AND OUTS TRIMS AND OUTS",
                "SHORT\rTrims and Outs",  # special case: "Trims and Outs" keeps casing
            ),  # repeated phrases should be deduped
            (
                "TITLES, BKGD, OVERLAYS",
                "TITLES, BKGD, Overlays",  # special case: "Overlays" keeps casing
            ),
        ]
        self.test_language_values = [
            ("english", "English"),
            ("ENGLISH ", "English"),  # trailing whitespace
            ("Englsh", "English"),  # misspelling
            ("German; English", "German, English"),  # semicolon delimiter
            ("French/German", "French, German"),  # slash delimiter
            ("Italian | Spanish", "Italian, Spanish"),  # pipe delimiter
            ("Spanish and Italian", "Spanish, Italian"),  # "and" delimiter
            ("Chinese & Japanese", "Chinese, Japanese"),  # ampersand delimiter
            ("Russian,Italian", "Russian, Italian"),  # improperly spaced comma
            ("English; English", "English"),  # repeated language should be deduped
            ("Portuguese for Brazil", "Portuguese"),  # special case, known value
            ("?", "Undetermined"),  # special case, known value
            ("Russian Intertitles", "Russian"),  # "Intertitles" should be removed
            ("N/A", "No linguistic content"),  # special case, known value
            (
                "N/A | English",
                "No linguistic content, English",
            ),  # "N/A" should be processed as "No linguistic content" and not split
        ]
        self.test_director_values = [
            (
                "OLEG LITVAK, william heick, R.J. CUTLER, MARY ANN DOANE, john a.b.c. doe",
                "Oleg Litvak, William Heick, R.J. Cutler, Mary Ann Doane, John A.B.C. Doe",
            ),  # capitalization variations
            (
                "Diego de la Texera, JOHN VAN DER DOE",
                "Diego de la Texera, John van der Doe",
            ),  # particles kept lowercase
            (
                "Richard Ray Perez and Lorena Parlee",
                "Richard Ray Perez, Lorena Parlee",
            ),  # "and" delimiter
            (
                "Debra Chasnoff\rKim Klausner\rMargaret Lazarus",
                "Debra Chasnoff, Kim Klausner, Margaret Lazarus",
            ),  # \r delimiter
            (
                "Ray Taylor & Lewis D. Collins",
                "Ray Taylor, Lewis D. Collins",
            ),  # ampersand delimiter
            (
                "Ford Beebe ; John Rawlins",
                "Ford Beebe, John Rawlins",
            ),  # semicolon delimiter
            (
                "Monogram Productions, Inc. ; a King Brothers production",
                "Monogram Productions, Inc. ; a King Brothers production",
            ),  # multiple delimiters--keep as-is
            ("n/a", "N/A"),  # special case, null value
            ("N/A", "N/A"),  # special case, null value
            ("N/a", "N/A"),  # special case, null value
            ("No Director listed", "N/A"),  # special case, null value
            ("null, NULL", "Unknown"),  # special case, null value
            ("unknown, UNKNOWN, Unknown", "Unknown"),  # special case, null value
            ("   ", "Unknown"),  # special case, empty value
            (
                "john director-doe",
                "John Director-Doe",
            ),  # special case, hyphenated surname
            (
                "Lew Landers (as Louis Friedlander)",
                "Louis Friedlander",
            ),  # credited name after parenthetical "as"
            (
                "JANE DIRECTOR AS STAGE NAME",
                "Stage Name",
            ),  # "as" delimiter, case-insensitive
            (
                "William Goodrich [i.e. Roscoe Arbuckle]",
                "William Goodrich",
            ),  # take name before bracketed i.e.
            (
                "Marcus aka Sid Marcus",
                "Marcus",
            ),  # take name before aka
            (
                "John Doe (aka John D)",
                "John Doe",
            ),  # take name before parenthetical aka
            (
                "Jane Doe, William Goodrich i.e. , Roscoe Arbuckle",
                "Jane Doe, William Goodrich",
            ),  # i.e. with space before comma does not split multivalue on that comma
        ]

    def test_production_type_mapping(self):
        for input, expected in self.test_production_type_values:
            with self.subTest(input=input, expected=expected):
                new_value = _apply_transformers("production_type", input)
                self.assertEqual(new_value, expected)

    def test_language_mapping(self):
        for input, expected in self.test_language_values:
            with self.subTest(input=input, expected=expected):
                new_value = _apply_transformers("Language", input)
                self.assertEqual(new_value, expected)

    def test_director_mapping(self):
        for input, expected in self.test_director_values:
            with self.subTest(input=input, expected=expected):
                new_value = _apply_transformers("director", input)
                self.assertEqual(new_value, expected)
