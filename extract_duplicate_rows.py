import argparse
import pandas as pd
from pathlib import Path


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data_file",
        help="Path to XLSX spreadsheet provided by FTVA",
        required=True,
    )
    parser.add_argument(
        "--tapes_tab_name",
        help="Name of the spreadsheet tab containing tape data",
        default="Tapes(row 4560-24712)",
    )
    parser.add_argument(
        "--output_duplicate_path",
        help="Path to the output spreadsheet for duplicate rows",
        default="duplicate_rows.xlsx",
    )
    parser.add_argument(
        "--remove_duplicates",
        help="If specified, remove duplicate rows from the spreadsheet in place",
        action="store_true",
    )
    args = parser.parse_args()
    return args


def _find_duplicate_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Find duplicate rows in the DataFrame based on the 'Legacy Path' column."""
    # Check if 'Legacy Path' column exists
    if "Legacy Path" not in df.columns:
        raise ValueError("The DataFrame does not contain a 'Legacy Path' column.")

    # Find duplicate rows based on the 'Legacy Path' column
    duplicate_rows = df[df.duplicated(subset=["Legacy Path"], keep=False)]

    return duplicate_rows


def _format_duplicate_rows(duplicate_rows: pd.DataFrame) -> pd.DataFrame:
    """Format duplicate rows for better readability in an output spreadsheet."""
    # Create a copy of the DataFrame to avoid modifying the original slice,
    # which causes pandas to raise a SettingWithCopyWarning
    duplicate_rows = duplicate_rows.copy()
    # Add a new column with the original row index
    duplicate_rows.reset_index(inplace=True, names="Original Row Number")
    # increment each index by 2 to match the original spreadsheet
    # (1 based index, plus header row)
    duplicate_rows["Original Row Number"] += 2

    return duplicate_rows


def _remove_duplicates_from_df(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate rows from the DataFrame."""
    # Remove duplicates based on 'Legacy Path' column, keeping the first occurrence
    # and dropping the rest
    df.drop_duplicates(subset=["Legacy Path"], keep="first", inplace=True)
    return df


def _remove_duplicates_from_spreadsheet(
    df: pd.DataFrame, data_file_path: Path, tapes_tab_name: str
) -> None:
    """Remove duplicate rows from the DataFrame and save it back to the spreadsheet."""
    # Remove duplicates from the DataFrame
    df = _remove_duplicates_from_df(df)
    # Save the cleaned DataFrame back to the spreadsheet;
    # only overwrite the specified tab, and keep the rest of the spreadsheet intact
    with pd.ExcelWriter(
        data_file_path, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        df.to_excel(writer, sheet_name=tapes_tab_name, index=False)
    print(f"Duplicate rows removed. Updated spreadsheet saved to {data_file_path}.")


def main():
    args = _get_args()
    data_file_path = Path(args.data_file)

    if not data_file_path.exists():
        raise FileExistsError("Data file does not exist")

    # check that tab exists within the spreadsheet
    xls = pd.ExcelFile(data_file_path)
    if args.tapes_tab_name not in xls.sheet_names:
        raise ValueError(
            f"Tab '{args.tapes_tab_name}' does not exist in the spreadsheet"
        )

    # Read the spreadsheet into a DataFrame
    df = pd.read_excel(data_file_path, sheet_name=args.tapes_tab_name)
    print(f"Data loaded from {data_file_path}, tab: {args.tapes_tab_name}.")

    # Find duplicate rows
    duplicate_rows = _find_duplicate_rows(df)
    if duplicate_rows.empty:
        print("No duplicate rows found.")
    else:
        print(f"{len(duplicate_rows)} duplicate rows found.")
        duplicate_rows = _format_duplicate_rows(duplicate_rows)
        duplicate_rows_path = Path(args.output_duplicate_path)
        duplicate_rows.to_excel(duplicate_rows_path, index=False)
        print(f"Duplicate rows saved to {duplicate_rows_path}.")

        # Optionally, remove duplicates
        if args.remove_duplicates:
            _remove_duplicates_from_spreadsheet(df, data_file_path, args.tapes_tab_name)


if __name__ == "__main__":
    main()
