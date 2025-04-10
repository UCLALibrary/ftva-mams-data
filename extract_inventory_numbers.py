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
    #
    # NOTE: the pattern works in most cases, but will return false positives
    # where the input contains a substring that syntactically matches pattern
    # but is not actually a valid inventory number, according to FTVA
    # e.g. AAC442\Title_T01ASYNC_Surround matches T01, which is a valid pattern,
    # but not an actual inventory number
    regex_components = [
        r'(?<![A-Z])',  # pattern not preceded by capital letter, to mitigate false positives
        r'(?:M|T|DVD|FE|HFA|VA|XFE|XFF|XVE)',  # non-capturing group of 8 prefixes defined by FTVA
        r'\d{2,}',  # 2 or more digits, as many as possible
        r'(?:[A-Z](?![A-Za-z]))?'  # optional suffix 1 capital letter not followed by another letter
    ]

    return re.compile(''.join(regex_components))


def _extract_inventory_numbers(
        value: str,
        inventory_number_pattern: re.Pattern = _compile_regex()
) -> str:
    """Returns a pipe-delimited list of matches against provided pattern."""
    if not isinstance(value, str):
        return

    matches = re.findall(inventory_number_pattern, value)
    if matches:
        # per FTVA spec, provide pipe-delimited string
        # if multiple matches in a single input value
        # uses dict.fromkeys() to get unique values
        # while maintaining list order
        return '|'.join(list(dict.fromkeys(matches)))
    return ''


def main() -> None:
    """Extracts inventory numbers from values in a spreadsheet provided by FTVA digital lab."""
    args = _get_args()

    input_file_path = Path(args.data_file)
    if not input_file_path.exists():
        raise FileExistsError("Data file does not exist")

    # The target sheet and column are hard-coded here
    # might want to move to set them up as arguments later
    df = pd.read_excel(args.data_file, sheet_name='Tapes(row 4560-24712)')
    # Using Pandas Series.apply() method here to apply function to target column
    # and store results in a new column
    df["Inventory Number [EXTRACTED]"] = df["Legacy Path"].apply(_extract_inventory_numbers)

    # Save new XLSX file with extracted inventory numbers
    output_path = Path(args.data_file).with_stem(input_file_path.stem + "_with_inventory_numbers")
    df.to_excel(output_path, index=False)


if __name__ == "__main__":
    main()
