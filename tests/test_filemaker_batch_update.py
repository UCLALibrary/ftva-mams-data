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

    def test_production_type_mapping(self):
        for input, expected in self.test_production_type_values:
            with self.subTest(input=input, expected=expected):
                new_value = _apply_transformers("production_type", input)
                self.assertEqual(new_value, expected)
