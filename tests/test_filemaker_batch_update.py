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
                "Diego de la Texera, John Van Der Doe",
                "Diego de la Texera, John Van Der Doe",
            ),  # Mixed-case remains as-is
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
            ("n/a", "N/A"),  # testing null value mapping
            ("N/A", "N/A"),  # testing null value mapping
            ("N/a", "N/A"),  # testing null value mapping
            ("No Director listed", "N/A"),  # testing null value mapping
            ("null, NULL", "Unknown"),  # testing null value mapping
            ("unknown, UNKNOWN, Unknown", "Unknown"),  # testing null value mapping
            ("   ", "Unknown"),  # empty value
            (
                "john director-doe",
                "John Director-Doe",
            ),  # hyphenated surname
            (
                "Lew Landers (as Louis Friedlander)",
                "Louis Friedlander",
            ),  # credited name after parenthetical "as"
            (
                "JANE DIRECTOR AS STAGE NAME",
                "Stage Name",
            ),  # credited name after case-insensitive "as"
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
            ),  # `i.e.` with space before comma should not split multivalue on that comma
            (
                "André De Toth (as Andre deToth)",
                "Andre deToth",
            ),  # name following "as" keeps casing
            (
                "David MacDonald, Mervyn LeRoy, John O'Brien Doe, LeeRoy Jenkins",
                "David MacDonald, Mervyn LeRoy, John O'Brien Doe, LeeRoy Jenkins",
            ),  # return names with internal capitalization as-is
            (
                "Ub Iwerks (uncredited)Shamus Culhane(co-director)",
                "Ub Iwerks (uncredited), Shamus Culhane(co-director)",
            ),  # insert `, ` between right parenthesis and uppercase letter
            (
                "1.Brad Bird\r2. Sam Raimi\r3.Jared Hess\r4. Adam Mckay",
                "1. Brad Bird, 2. Sam Raimi, 3. Jared Hess, 4. Adam Mckay",
            ),  # capitalize numbered names
            (
                "Richard Gerdau ;",
                "Richard Gerdau",
            ),  # bad trailing delimiter should not yield empty values
            (
                ", Wally Bulloch",
                "Wally Bulloch",
            ),  # bad leading delimiter should not yield empty values
            (
                "John Smith, Tom Jones,",
                "John Smith, Tom Jones",
            ),  # trailing comma should get stripped
            (
                "John Smith,, Tom Jones",
                "John Smith, Tom Jones",
            ),  # bad delimiters in middle of value should not yield empty values
            (
                "John Smith,Tom Jones",
                "John Smith, Tom Jones",
            ),  # delimiter missing space should get replaced with delimiter + space
            (
                "John Smith, Tom Jones \r\r",
                "John Smith, Tom Jones",
            ),  # trailing carriage returns should get stripped
            (
                "Mashuq M Deen, Dawn D Deason",
                "Mashuq M. Deen, Dawn D. Deason",
            ),  # single initials should get trailing dot
            (
                "Alex Alferov c/o All Media",
                "Alex Alferov c/o All Media",
            ),  # special token "c/o" should be lowercase
            (
                "1.JOHN A.B.C. DOE; jane doe (credited as jane star); LeeRoy Jenkins",
                "1. John A.B.C. Doe, Jane Star, LeeRoy Jenkins",
            ),  # composite test: multiple transformations
        ]
        self.test_date_values = [
            ("1999", "1999"),  # valid year, no transform needed
            ("1999-01-01", "1999-01-01"),  # valid date, no transform needed
            ("1974 ", "1974"),  # trailing whitespace
            ("n/a", "N/A"),  # special case, known value
            ("UUUU", "Unknown"),  # special case, known value
            ("nd", "Unknown"),  # special case, known value
            ("?", "Unknown"),  # special casem known value
            ("[1992]", "1992"),  # brackets should be removed
            ("(1992)", "1992"),  # parentheses should be removed
            ("c 1939", "c1939"),  # normalize copyright format
            ("COPYRIGHT 2007", "c2007"),
            ("C1988", "c1988"),
            ("c1978", "c1978"),
            ("CIRCA 1970", "1970?"),  # normalize circa format
            ("ca. 1950", "1950?"),
            ("CA. 2020", "2020?"),
            ("circa 1925", "1925?"),
            ("circa 1920-1930", "1920 or 1930"),  # circa range format
            ("January 1956", "1956-01"),  # convert natural language date
            ("Feb 1967", "1967-02"),
            ("Mar 24 1953", "1953-03-24"),
            ("June 28, 1975", "1975-06-28"),
            ("06/15/1980", "1980-06-15"),  # normalize date format
            ("03-25-1990", "1990-03-25"),
            ("04/1985", "1985-04"),
            ("19", "19--?"),  # partial year with two digits
            ("20-", "20--"),  # partial year with two digits and trailing hyphen
            ("195-", "195-"),  # partial year with three digits but no question mark
            (
                "196-?",
                "196-?",
            ),  # partial year with three digits, dash, and question mark, no modification
            ("1990s", "199-"),  # decade
            ("19??", "19--?"),  # partial year with two digits and question marks
            ("1946?", "1946?"),  # partial year with four digits and ?, no modification
            ("195?", "195?"),  # partial year with three digits and ?, no modification
            ("197u", "197-"),  # partial year with single u/x placeholder
            ("20UU", "20--?"),  # partial year with two placeholders
            ("19uu", "19--?"),
            ("20XX", "20--?"),
            ("19uu-1971", "19--?-1971"),  # handle partial year ranges with placeholders
            ("19UU-UUUU", "19--?"),  # partial range, collapses to single indeterminate
            ("1955/1956", "1955-1956"),  # handle various date range formats
            ("[2011-13]", "2011-2013"),
            ("1959 - 1963", "1959-1963"),
            ("1975-76", "1975-1976"),
            ("2015-03-12", "2015-03-12"),  # valid date, no transform needed
            ("1939-11-28", "1939-11-28"),
            ("JUNE 28-29", "JUNE 28-29"),  # date range of days should not be modified
            ("MAY 9-10, 1980", "MAY 9-10, 1980"),
            ("APRIL 30 & MAY 1-3, 1980", "APRIL 30 & MAY 1-3, 1980"),
            ("October 17 & 18, 1989", "October 17 & 18, 1989"),
            ("MAY 7,8 & 9", "MAY 7,8 & 9"),
            ("FALL 1978", "FALL 1978"),  # season and year should not be modified
            (
                "11-12-1959, 11-19-1959",
                "11-12-1959, 11-19-1959",
            ),  # don't modify lists of dates
            ("04-02-1959, 04-09-1959", "04-02-1959, 04-09-1959"),
            (
                "C. 1970s",
                "197-?",
            ),  # decade with circa should be normalized to decade format
            (
                "ca. 1920’s?",
                "192-?",
            ),  # decade with circa and question mark should be normalized to decade format
            (
                "1960-1970s",
                "1960-1970",
            ),  # decade range should be normalized to decade format
            (
                "10-09-1995\r10-14-2002",
                "10-09-1995\r10-14-2002",
            ),  # multiple dates separated by carriage return should not be modified
            ("1924 circa", "1924?"),  # circa after date should be normalized
            (
                "c 1978.",
                "c1978",
            ),  # period after year should be removed in copyright format
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

    def test_date_mapping(self):
        for input, expected in self.test_date_values:
            with self.subTest(input=input, expected=expected):
                new_value = _apply_transformers("record_date", input)
                self.assertEqual(new_value, expected)
