import unittest
from extract_inventory_numbers import _extract_inventory_numbers


class TestRegEx(unittest.TestCase):

    def test_regex(self):
        # test cases comprised of tuples
        # where the first item is the input string
        # and the second item is the expected output derived from FTVA specs
        test_cases = (
            ("HFA27M_Reel", "HFA27M"),
            ("VA13161T_KTLA", "VA13161T"),
            ("M190816Medea2", "M190816"),
            ("DVD13360_HouseOfCats_FromDVD_SD_2997FPS_VOB", "DVD13360"),
            ("GeraldMcBoingBoingShow_T119482_DerTeamfromZwisendorpff", "T119482"),
            ("XFE1915MX", "XFE1915"),  # invalid suffix case
            ("Randy_Requiem1", ""),  # no matching inv # in this case, so should be empty string
            (
                "XFE4098M_XFF104M_DamagedLives_Finals",
                "XFE4098M|XFF104M"
            ),  # multi-match to pipe-delimited string case
            (
                "XVE779T_ZVE780T_OneNightStand_WorldOfLennyBruce_CaptureFiles_SD_2997FPS_YUV",
                "XVE779T"
            ),  # XVE is a valid prefix, but ZVE isn't, so only 1 valid inv # in input
            ("Max_From_DVD_H264", ""),  # input has pattern look-alike (H264), but no valid inv #
            ("HARVEST3000AUDIOMAG", ""),  # like last case, look-alike in middle, but no valid inv #
            (
                "M46293SanFernandoCLEANEXPORT3",
                "M46293"
            ),  # contains valid inv # (M46293), but also look-alike (T3)
            # flake8 flagged escape seq (\T), hence raw strings in following cases
            (
                r"AAC424\T70123_50Years_Kids_Programming\T70123_50Years_T1",
                "T70123"
            ),  # per FTVA, inv #s have 2 or more digits, so T70123 is good, but T1 is invalid
            (
                r"AAC442\Title_T01ASYNC_Surround",
                "T01"
            )  # known false positive--T01 is syntactically valid, but not actual inv #, per FTVA
        )

        for input, output in test_cases:
            inventory_numbers = _extract_inventory_numbers(input)
            self.assertEqual(inventory_numbers, output)
