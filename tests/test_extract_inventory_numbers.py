import unittest
import re
from extract_inventory_numbers import _compile_regex


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
            )  # contains valid inv # (M46293), but also look-alike (T3)
        )

        inventory_number_pattern = _compile_regex()
        for input, output in test_cases:
            matches = re.findall(inventory_number_pattern, input)
            self.assertEqual('|'.join(matches), output)
