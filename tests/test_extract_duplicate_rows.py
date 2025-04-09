import unittest
from extract_duplicate_rows import (
    _find_duplicate_rows,
    _format_duplicate_rows,
    _remove_duplicates_from_df,
)
import pandas as pd


class TestFormatDuplicateRows(unittest.TestCase):

    def setUp(self):
        self.df = pd.DataFrame(
            {
                "Legacy Path": [
                    "path/to/file1",
                    "path/to/file1",  # Duplicate
                    "path/to/file2",
                    "path/to/file3",
                    "path/to/file3",  # Duplicate
                ],
                "Other Column": [1, 2, 3, 4, 5],
            }
        )

    def test_format_duplicate_rows(self):
        duplicate_rows = _find_duplicate_rows(self.df)
        formatted_rows = _format_duplicate_rows(duplicate_rows)
        expected_output = pd.DataFrame(
            {
                # "Original Row Number" is the index of the original DataFrame + 2
                # to account for 1-based indexing and the header row
                "Original Row Number": [2, 3, 5, 6],
                "Legacy Path": [
                    "path/to/file1",
                    "path/to/file1",
                    "path/to/file3",
                    "path/to/file3",
                ],
                "Other Column": [1, 2, 4, 5],
            }
        )
        pd.testing.assert_frame_equal(formatted_rows, expected_output)

    def test_format_duplicate_rows_no_duplicates(self):
        # Test with a DataFrame that has no duplicates
        no_duplicates_df = pd.DataFrame(
            {
                "Legacy Path": ["path/to/file1", "path/to/file2", "path/to/file3"],
                "Other Column": [1, 2, 3],
            }
        )
        no_duplicates_df = _find_duplicate_rows(no_duplicates_df)
        formatted_rows = _format_duplicate_rows(no_duplicates_df)
        self.assertTrue(formatted_rows.empty)
        self.assertIn("Original Row Number", formatted_rows.columns)


class TestRemoveDuplicatesFromDf(unittest.TestCase):
    def setUp(self):
        self.df_with_duplicates = pd.DataFrame(
            {
                "Legacy Path": [
                    "path/to/file1",
                    "path/to/file2",
                    "path/to/file1",  # Duplicate
                    "path/to/file3",
                    "path/to/file2",  # Duplicate
                ],
                "Other Column": [1, 2, 3, 4, 5],
            }
        )
        self.df_without_duplicates = pd.DataFrame(
            {
                "Legacy Path": [
                    "path/to/file1",
                    "path/to/file2",
                    "path/to/file3",
                ],
                "Other Column": [1, 2, 4],
            }
        )

    def test_remove_duplicates_from_df(self):
        cleaned_df = _remove_duplicates_from_df(self.df_with_duplicates)
        expected_df = pd.DataFrame(
            {
                "Legacy Path": [
                    "path/to/file1",
                    "path/to/file2",
                    "path/to/file3",
                ],
                "Other Column": [1, 2, 4],
            },
            index=[0, 1, 3],
        )
        pd.testing.assert_frame_equal(cleaned_df, expected_df)

    def test_remove_duplicates_from_df_no_duplicates(self):
        cleaned_df = _remove_duplicates_from_df(self.df_without_duplicates)
        pd.testing.assert_frame_equal(cleaned_df, self.df_without_duplicates)
