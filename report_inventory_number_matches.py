import argparse
import csv
import json
import pandas as pd
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path


@dataclass
class InventoryNumberData:
    """Class for simplifying management of large sets of
    inventory numbers from legacy systems.
    """

    source_system: str
    # Dictionary keyed on normalized inventory number, along with a list
    # of the record-specific identifier(s) associated with that key.
    # These can be Alma holdings ids, Filemaker record ids, or Google Sheet
    # row numbers.
    identifiers: defaultdict[str, list[str]]
    _singletons: set[str] = None

    @cached_property
    # This gets used a few times, but doesn't change, so cache it.
    def singletons(self) -> set[str]:
        self._singletons = self._get_singletons()
        return self._singletons

    def _get_singletons(self) -> set[str]:
        """Returns a set of id keys (inventory numbers) which occur only once
        in their source data.
        """
        return {key for key, val in self.identifiers.items() if len(val) == 1}

    def print_summary_counts(self) -> None:
        """Prints various counts about the object's identifiers."""
        total_count = sum([len(val) for val in self.identifiers.values()])
        distinct_count = len(self.identifiers)
        singleton_count = len(self.singletons)
        # Many Google sheet records have no inventory number, though Alma and FM data always do.
        # self.identifiers is a defaultdict, so be careful querying it;
        # len(self.identifiers[""]) adds an entry, if "" is not already a key!
        if "" in self.identifiers:
            empty_count = len(self.identifiers[""])
        else:
            empty_count = 0
        print(
            f"Counts for {self.source_system} inventory numbers: {total_count} total, "
            f"{distinct_count} distinct, {singleton_count} singletons, {empty_count} empty"
        )


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


def _get_alma_data(filename: str) -> InventoryNumberData:
    """Returns an InventoryNumberData object with data keyed on the
    normalized Alma permanent call number, along with a list of the
    Alma holdings id(s) associated with that key.
    """
    with open(filename, "r") as f:
        data = csv.DictReader(f)
        data = [row for row in data]
    alma_identifiers = defaultdict(list)
    for row in data:
        # Many Alma values have spaces; remove them.
        inventory_no = row["Permanent Call Number"].replace(" ", "")
        alma_identifiers[inventory_no].append(row["Holding Id"])

    alma_data = InventoryNumberData(source_system="Alma", identifiers=alma_identifiers)
    alma_data.print_summary_counts()
    return alma_data


def _get_filemaker_data(filename: str) -> InventoryNumberData:
    """Returns an InventoryNumberData object with data keyed on the
    normalized Filemaker inventory number, along with a list of the
    Filemaker record id(s) associated with that key.
    """
    with open(filename, "r") as f:
        data = json.load(f)
    # Some Filemaker inventory numbers end with (or in 1 case, contain...)
    # u'\xa0', non-breaking space.  Almost certainly errors; remove this character.
    filemaker_identifiers = defaultdict(list)
    for row in data:
        inventory_no = row["inventory_no"].replace("\xa0", "")
        filemaker_identifiers[inventory_no].append(row["recordId"])

    filemaker_data = InventoryNumberData(
        source_system="Filemaker", identifiers=filemaker_identifiers
    )
    filemaker_data.print_summary_counts()
    return filemaker_data


def _get_google_data(filename: str) -> InventoryNumberData:
    """Returns an InventoryNumberData object with data keyed on the
    normalized Google inventory number, along with a list of the
    row number(s) associated with that key.
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
            # Convert these to string, same as the associated values from other sources.
            google_identifiers[inventory_no].append(str(index + 2))

    google_data = InventoryNumberData(
        source_system="Google", identifiers=google_identifiers
    )
    google_data.print_summary_counts()
    return google_data


def report_perfect_matches(
    data: list[InventoryNumberData], message: str, report_filename: str, sheet_name: str
) -> None:
    """Given a list of InventoryNumberData objects, report on the "perfect matches":
    the values which occur only once each, in all of the input data.
    """
    singletons = [obj.singletons for obj in data]
    matches = set.intersection(*singletons)
    print(f"{message}: {len(matches)}")

    # Add it to the Excel file.
    write_excel_report(filename=report_filename, sheet_name=sheet_name, data=matches)


def report_unmatched(data: list[InventoryNumberData], report_filename: str) -> None:
    """Given a list of InventoryNumberData objects, report on the inventory numbers
    (and their related identifiers) where the inventory number occurs in only one
    of the dictionaries.
    """
    # These are not unique, across all sources.
    all_inventory_nos = [key for obj in data for key in obj.identifiers]  # 814077
    # TODO: Debug; why does 814077 not match 814075, total of "distinct" counts?
    # print("In report unmatched, 2nd loop thru data")
    # for obj in data:
    #     print(obj.source_system, len(obj.identifiers))
    #     obj.print_summary_counts()

    # These are unique, and creating a set makes the next step much faster than a list.
    all_unmatched_inventory_nos = {
        key for key, val in Counter(all_inventory_nos).items() if val == 1
    }

    for obj in data:
        # Get the identifiers (inventory numbers and associated values) unique to this object.
        unmatched_inventory_nos = {
            key: val
            for key, val in obj.identifiers.items()
            if key in all_unmatched_inventory_nos
        }

        sheet_name = f"Only in {obj.source_system}"
        column_names = ["Inventory Number", "Other Identifiers"]
        print(f"{sheet_name}: {len(unmatched_inventory_nos)}")
        write_excel_report(
            filename=report_filename,
            sheet_name=sheet_name,
            data=unmatched_inventory_nos,
            column_names=column_names,
        )


def _create_dataframe(data: list | set | dict, column_names: list[str]) -> pd.DataFrame:
    """Helper method to create pandas dataframe from a set / list or a dict,
    since pandas does that in different ways.
    """
    if isinstance(data, list | set):
        # Sort it for more useable output; converts set to list, which is fine.
        data = sorted(data)
        # Easy dataframe construction.
        df = pd.DataFrame(data, columns=column_names)
    elif isinstance(data, dict):
        # dicts need some manipulation.
        # Sort it, which also is different from sets.
        data = dict(sorted(data.items()))

        # The dict key will become the index column, so split column names into
        # first column and the rest.
        index_column_name = column_names[0]
        other_column_names = column_names[1:]

        # The values of these dicts are lists, which pandas dataframe does not like;
        # convert each value to a string.
        data = {key: "|".join(value) for key, value in data.items()}

        # Can't just pass the dict to the df, must use from_dict();
        # orient="index" means use the keys as rows, not columns.
        df = pd.DataFrame.from_dict(data, orient="index", columns=other_column_names)

        # Finally, set the df's built-in index column name to the one we want.
        df.reset_index(names=index_column_name, inplace=True)
    else:
        raise TypeError(f"Unexpected type: {type(data)}")
    return df


def write_excel_report(
    filename: str,
    sheet_name: str,
    data: set | dict,
    column_names: list[str] = None,
) -> None:
    if column_names is None:
        column_names = ["Inventory Number"]

    df = _create_dataframe(data, column_names)
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

    alma_data = _get_alma_data(args.alma_file)
    filemaker_data = _get_filemaker_data(args.filemaker_data_file)
    google_data = _get_google_data(args.google_file)

    report_filename = "inventory_number_matches.xlsx"

    report_perfect_matches(
        data=[alma_data, filemaker_data, google_data],
        message="Perfect matches for all 3 sources",
        report_filename=report_filename,
        sheet_name="All 3 sources",
    )

    report_perfect_matches(
        data=[alma_data, filemaker_data],
        message="Perfect matches for Alma and Filemaker",
        report_filename=report_filename,
        sheet_name="Alma and FM only",
    )

    report_perfect_matches(
        data=[alma_data, google_data],
        message="Perfect matches for Alma and Google",
        report_filename=report_filename,
        sheet_name="Alma and Google only",
    )

    report_perfect_matches(
        data=[filemaker_data, google_data],
        message="Perfect matches for Filemaker and Google",
        report_filename=report_filename,
        sheet_name="FM and Google only",
    )

    report_unmatched(
        data=[alma_data, filemaker_data, google_data], report_filename=report_filename
    )


if __name__ == "__main__":
    main()
