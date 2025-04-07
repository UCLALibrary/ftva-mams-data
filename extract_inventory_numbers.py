import argparse
import re
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
    args = parser.parse_args()
    return args


def _compile_regex() -> re.Pattern:
    # Return a compiled RegEx pattern for matching inventory numbers
    # the RegEx is comprised of three main parts, which are explained inline below
    regex_components = [
        r'(?:M|T|DVD|HFA|VA|XFE|XFF|XVE)',  # non-capturing group of 8 prefixes defined by FTVA
        r'\d+',  # 1 or more digits, as many as possible
        r'(?:[A-Z](?![A-Za-z]))?'  # optional suffix 1 capital letter not followed by another letter
    ]

    return re.compile(''.join(regex_components))


def _extract_inventory_numbers(df: pd.DataFrame) -> pd.DataFrame:

    inventory_number_pattern = _compile_regex()

    # Priority in which to consider columns,
    # per instructions from FTVA
    column_priority = ('Source Inventory #', 'File Name', 'Sub Folder', 'File Folder Name')
    existing_inventory_number_values = []

    for index, row in df.iterrows():
        # The header row in the source spreadsheet is repeated many times
        # as if multiple sheets were appended together
        # this condition checks if the current value in the Inventory # column is:
        # 1) not a header, and;
        # 2) not NaN
        # meaning it is some other value
        # row indexes for any such values are then appended to a list to be printed for reference
        if (not row['Inventory #'] == 'Inventory #') and (not pd.isna(row['Inventory #'])):
            existing_inventory_number_values.append(index)

        for column in column_priority:
            if not isinstance(row[column], str):
                continue

            matches = re.findall(inventory_number_pattern, row[column])
            if matches:
                # per FTVA spec, provide pipe-delimited string
                # if multiple matches in a single input value
                row['Inventory #'] = '|'.join(matches)
                break  # we only want the first match in a row
    print(df.iloc[existing_inventory_number_values]['Inventory #'])
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
