import argparse
import re
import pandas as pd
from pathlib import Path

# Regular expression to match inventory numbers,
# per FTVA specification
INVENTORY_NUMBER_PATTERN = re.compile(r'(?:M|T|DVD|HFA|VA|XFE|XFF|XVE)\d+(?:[A-Z](?![A-Za-z]))?')


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data_file",
        help="Path to XLSX spreadsheet provided by FTVA",
        required=True,
    )
    args = parser.parse_args()
    return args


def _extract_inventory_numbers(df: pd.DataFrame) -> pd.DataFrame:
    # Priority in which to consider columns,
    # per instructions from FTVA
    column_priority = ('Source Inventory #', 'File Name', 'Sub Folder', 'File Folder Name')

    for index, row in df.iterrows():
        for column in column_priority:
            if not isinstance(row[column], str):
                continue

            matches = re.findall(INVENTORY_NUMBER_PATTERN, row[column])
            if matches:
                # per FTVA spec, provide pipe-delimited string
                # if multiple matches in a single input value
                row['Inventory #'] = '|'.join(matches)
                break  # we only want the first match in a row
    return df


def main() -> None:
    """Extracts inventory numbers from values in a spreadsheet provided by FTVA digital lab."""
    args = _get_args()

    input_file_path = Path(args.data_file)
    if not input_file_path.exists():
        raise FileExistsError("Data file does not exist")

    df = pd.read_excel(args.data_file, sheet_name='Source Data', header=1)
    df_with_inventory_numbers = _extract_inventory_numbers(df)

    # Save new XLSX file with extracted inventory numbers
    output_path = Path(args.data_file).with_stem(input_file_path.stem + "_with_inventory_numbers")
    df_with_inventory_numbers.to_excel(output_path, index=False)


if __name__ == "__main__":
    main()
