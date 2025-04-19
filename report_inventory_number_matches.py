import argparse
import csv
import json
from pathlib import Path
import pandas as pd
from collections import Counter
from itertools import chain


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alma_file",
        help="Path to CSV file containing FTVA Alma holdings data",
        required=True,
    )
    parser.add_argument(
        "--filemaker_data_file",
        help="Path to JSON file containing FTVA Filemaker data",
        required=True,
    )
    parser.add_argument(
        "--google_file",
        help="Path to XLSX file containing FTVA Google Sheets data",
        required=True,
    )
    args = parser.parse_args()
    return args


def _get_alma_identifiers(filename: str) -> list[str]:
    with open(filename, "r") as f:
        alma_data = csv.DictReader(f)
        alma_data = [row for row in alma_data]
    # Many Alma values have spaces; remove them.
    alma_identifiers = [
        row["Permanent Call Number"].replace(" ", "") for row in alma_data
    ]
    return alma_identifiers


def _get_filemaker_identifiers(filename: str) -> list[str]:
    with open(filename, "r") as f:
        filemaker_data = json.load(f)
    # Some Filemaker inventory numbers end with (or in 1 case, contain...)
    # u'\xa0', non-breaking space.  Almost certainly errors; remove this character.
    filemaker_identifiers = [
        row["inventory_no"].replace("\xa0", "") for row in filemaker_data
    ]
    return filemaker_identifiers


def _get_google_identifiers(filename: str) -> list[str]:
    # The target sheet and column are hard-coded here;
    # might want to move to set them up as arguments later.
    df = pd.read_excel(filename, sheet_name="Tapes(row 4560-24712)", dtype="string")
    # Convert the missing (None) values to empty strings for the column we need.
    df = df.fillna(value={"Inventory Number [EXTRACTED]": ""})
    # Convert the dataframe to a list of dictionaries, one for each row.
    google_data = df.to_dict(orient="records")
    # Some Google cells have multiple values, pipe-delimited; separate them.
    cells = [row["Inventory Number [EXTRACTED]"].split("|") for row in google_data]
    # cells is now a list of lists, like [["M123"], [""], ["M234", "M345"]]
    # Unpack this into a flat list of all values.  Using itertools.chain is arguably
    # easier to understand than nested list comprehension, plus it's cool....
    google_identifiers = [*chain(*cells)]
    return google_identifiers


def _get_singletons(data: list) -> set[str]:
    """Returns a set of values which occur only once in the input list."""
    counts = Counter(data)
    return {value for value, count in counts.items() if count == 1}


def get_perfect_matches(data: list[set[str]]) -> set[str]:
    """Given a list of sets, return a set containing values
    which occur only once in all of the input set.
    """
    return set.intersection(*data)
    pass


def print_summary_counts(data: list, data_description: str) -> None:
    total_count = len(data)
    unique_count = len(set(data))
    singleton_count = len(_get_singletons(data))
    empty_count = len([val for val in data if not val])
    print(
        f"Counts for {data_description}: {total_count} total, "
        f"{unique_count} unique, {singleton_count} singletons, {empty_count} empty"
    )


def print_match_counts(
    alma_identifiers: list, filemaker_identifiers: list, google_identifiers: list
) -> None:
    # Report the 1-to-1 and 1-to-1-to-1 matches first.
    # alma_singletons = _get_singletons(alma_identifiers)
    pass


def write_excel_report(
    filename: str,
    sheet_name: str,
    data: set | list[list],
    column_names: list[str] = None,
) -> None:
    if column_names is None:
        column_names = ["Inventory_Number"]

    # Sort the data, which for this data is not perfect but better than random.
    df = pd.DataFrame(sorted(data), columns=column_names)

    # pandas.ExcelWriter apparently needs to know in advance if the file exists,
    # and is finicky about other settings too.
    if Path(filename).exists():
        # openpxyl only: pandas (as of 2.2.3) does not support appending with xlsxwriter.
        other_params = {"mode": "a", "if_sheet_exists": "replace"}
    else:
        other_params = {"mode": "w"}

    # Add the data to the file in the given sheet, updating the file
    # if it already exists. Do not write an index column, just the data.
    with pd.ExcelWriter(filename, engine="openpyxl", **other_params) as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def main() -> None:
    args = _get_args()

    alma_identifiers = _get_alma_identifiers(args.alma_file)
    print_summary_counts(alma_identifiers, "Alma inventory numbers")

    filemaker_identifiers = _get_filemaker_identifiers(args.filemaker_data_file)
    print_summary_counts(filemaker_identifiers, "Filemaker inventory numbers")

    google_identifiers = _get_google_identifiers(args.google_file)
    print_summary_counts(google_identifiers, "Google inventory numbers")

    print_match_counts(alma_identifiers, filemaker_identifiers, google_identifiers)

    alma_singletons = _get_singletons(alma_identifiers)
    filemaker_singletons = _get_singletons(filemaker_identifiers)
    google_singletons = _get_singletons(google_identifiers)

    report_filename = "inventory_number_matches.xlsx"

    matches = get_perfect_matches(
        [alma_singletons, filemaker_singletons, google_singletons]
    )
    print(f"Perfect matches for all 3 sources: {len(matches)}")
    write_excel_report(
        filename=report_filename, sheet_name="All 3 sources", data=matches
    )

    matches = get_perfect_matches([alma_singletons, filemaker_singletons])
    print(f"Perfect matches for Alma and Filemaker: {len(matches)}")
    write_excel_report(
        filename=report_filename, sheet_name="Alma and FM only", data=matches
    )

    # matches = get_perfect_matches([alma_singletons, google_singletons])
    # print(f"Perfect matches for Alma and Google: {len(matches)}")
    # matches = get_perfect_matches([filemaker_singletons, google_singletons])
    # print(f"Perfect matches for Filemaker and Google: {len(matches)}")

    # python report_inventory_number_matches.py \
    #     --alma_file ftva_holdings_20250417.csv \
    #     --filemaker_data_file filemaker_data_20250416_214936.json \
    #     --google_file google_sheet_20250416.xlsx


if __name__ == "__main__":
    main()
