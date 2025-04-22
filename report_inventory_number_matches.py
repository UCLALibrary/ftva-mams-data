import argparse
import csv
import json
import pandas as pd
from collections import Counter, defaultdict
from pathlib import Path
from typing import TypeAlias

# For simpler function signatures
id_dict: TypeAlias = dict[str, list[str]]
named_id_dict: TypeAlias = dict[str, id_dict]


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


def _get_alma_identifiers(filename: str) -> id_dict:
    """Returns a dict keyed on the normalized Alma permanent call number,
    along with a list of the Alma holdings id(s) associated with that key.
    """
    with open(filename, "r") as f:
        alma_data = csv.DictReader(f)
        alma_data = [row for row in alma_data]
    alma_identifiers = defaultdict(list)
    for row in alma_data:
        # Many Alma values have spaces; remove them.
        inventory_no = row["Permanent Call Number"].replace(" ", "")
        alma_identifiers[inventory_no].append(row["Holding Id"])

    print_summary_counts(alma_identifiers, "Alma inventory numbers")
    return alma_identifiers


def _get_filemaker_identifiers(filename: str) -> id_dict:
    """Returns a dict keyed on the normalized Filemaker inventory number,
    along with a list of the Filemaker record id(s) associated with that key.
    """
    with open(filename, "r") as f:
        filemaker_data = json.load(f)
    # Some Filemaker inventory numbers end with (or in 1 case, contain...)
    # u'\xa0', non-breaking space.  Almost certainly errors; remove this character.
    filemaker_identifiers = defaultdict(list)
    for row in filemaker_data:
        inventory_no = row["inventory_no"].replace("\xa0", "")
        filemaker_identifiers[inventory_no].append(row["recordId"])

    print_summary_counts(filemaker_identifiers, "Filemaker inventory numbers")
    return filemaker_identifiers


def _get_google_identifiers(filename: str) -> id_dict:
    """Returns a dict keyed on the normalized Google inventory number,
    along with a list of row number(s) associated with that key.
    """
    # The target sheet and column are hard-coded here;
    # might want to make them arguments later.
    df = pd.read_excel(filename, sheet_name="Tapes(row 4560-24712)", dtype="string")
    # Convert the missing (None) values to empty strings for the column we need.
    df = df.fillna(value={"Inventory Number [EXTRACTED]": ""})
    google_identifiers = defaultdict(list)
    for index, row in df.iterrows():
        # Some Google cells have multiple values, pipe-delimited; separate them.
        inventory_nos = row["Inventory Number [EXTRACTED]"].split("|")
        for inventory_no in inventory_nos:
            # dataframe indexes are 0-based, and there's a header row in the sheet;
            # add 2 to index to get row number shown in actual sheet.
            google_identifiers[inventory_no].append(index + 2)

    print_summary_counts(google_identifiers, "Google inventory numbers")
    return google_identifiers


def _get_singletons(data: id_dict) -> set[str]:
    """Returns a set of id keys (inventory numbers) which occur only once
    in their source data.
    """
    return {key for key, val in data.items() if len(val) == 1}


def print_summary_counts(data: id_dict, data_description: str) -> None:
    """Prints various counts about the given data."""
    total_count = sum([len(val) for val in data.values()])
    distinct_count = len(data)
    singleton_count = len(_get_singletons(data))
    # Many Google sheet records have no inventory number, though Alma and FM data always do.
    empty_count = len(data[""])
    print(
        f"Counts for {data_description}: {total_count} total, "
        f"{distinct_count} distinct, {singleton_count} singletons, {empty_count} empty"
    )


def report_perfect_matches(
    data: list[set[str]], message: str, report_filename: str, sheet_name: str
) -> None:
    """Given a list of sets, report on the "perfect matches":
    the values which occur in all of the input sets.
    """
    matches = set.intersection(*data)
    print(f"{message}: {len(matches)}")
    write_excel_report(filename=report_filename, sheet_name=sheet_name, data=matches)


def report_unmatched(data: list[named_id_dict]) -> None:
    """Given a list of named dictionaries, report on the keys (and their values)
    where the key occurs in only one of the dictionaries.
    """
    # Find the keys which occur just once across all input dictionaries.
    # Each input dictionary has a single key, like {"alma": id_dict};
    # here, we need the keys from id_dict, the value in the named_id_dict.
    # Example data:
    # [
    #   {'alma': {'inv_no_1': [1, 2, 3]}},
    #   {'google': {'inv_no_1': [4, 5, 6], 'inv_no_2': [7, 8, 9]}}
    # ]
    # Result: [inv_no_1, inv_no_1, inv_no_2]
    all_inventory_nos = [
        key for dict in data for nested_dict in dict for key in nested_dict
    ]
    unmatched_inventory_nos = [
        key for key, val in Counter(all_inventory_nos).items() if val == 1
    ]
    # Now, for each of the input dictionaries, get the


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
    filemaker_identifiers = _get_filemaker_identifiers(args.filemaker_data_file)
    google_identifiers = _get_google_identifiers(args.google_file)

    alma_singletons = _get_singletons(alma_identifiers)
    filemaker_singletons = _get_singletons(filemaker_identifiers)
    google_singletons = _get_singletons(google_identifiers)

    # We don't need these large full data sets any more; rmeove from memory.
    del (alma_identifiers, filemaker_identifiers, google_identifiers)

    report_filename = "inventory_number_matches.xlsx"

    report_perfect_matches(
        data=[alma_singletons, filemaker_singletons, google_singletons],
        message="Perfect matches for all 3 sources",
        report_filename=report_filename,
        sheet_name="All 3 sources",
    )

    report_perfect_matches(
        data=[alma_singletons, filemaker_singletons],
        message="Perfect matches for Alma and Filemaker",
        report_filename=report_filename,
        sheet_name="Alma and FM only",
    )

    report_perfect_matches(
        data=[alma_singletons, google_singletons],
        message="Perfect matches for Alma and Google",
        report_filename=report_filename,
        sheet_name="Alma and Google only",
    )

    report_perfect_matches(
        data=[filemaker_singletons, google_singletons],
        message="Perfect matches for Filemaker and Google",
        report_filename=report_filename,
        sheet_name="FM and Google only",
    )

    report_unmatched(data=[alma_singletons, filemaker_singletons, google_singletons])


# python report_inventory_number_matches.py \
#     --alma_file ftva_holdings_20250417.csv \
#     --filemaker_data_file filemaker_data_20250416_214936.json \
#     --google_file google_sheet_20250416.xlsx


if __name__ == "__main__":
    main()
