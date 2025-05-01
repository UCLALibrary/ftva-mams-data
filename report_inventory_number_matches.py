import argparse
import csv
import json
import pandas as pd
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TypeAlias

# For simpler function signatures
id_dict: TypeAlias = dict[str, list[str]]


@dataclass
class InventoryNumberData:
    """Class for simplifying management of large sets of
    inventory numbers from legacy systems (Alma and Filemaker);
    not used for Google Sheet data.
    """

    # The source system, used for reporting.
    source_system: str
    # What the identifier represents: holdings ids (Alma) or record ids (Filemaker).
    identifier_label: str
    # Dictionary keyed on normalized inventory number, along with a list
    # of the record-specific identifier(s) associated with that key.
    # These can be Alma holdings ids or Filemaker record ids.
    identifiers: id_dict
    # Keys in identifiers which are associated with one record in the source system.
    _singletons: set[str] = field(default_factory=set)
    # Keys in identifiers which are associated with multiple records in the source system.
    _repeats: set[str] = field(default_factory=set)

    @cached_property
    # This gets used a few times, but doesn't change, so cache it.
    def singletons(self) -> set[str]:
        self._singletons = self._get_singletons()
        return self._singletons

    @cached_property
    # This gets used a few times, but doesn't change, so cache it.
    def repeats(self) -> set[str]:
        self._repeats = self._get_repeats()
        return self._repeats

    def _get_singletons(self) -> set[str]:
        """Returns a set of id keys (inventory numbers) which occur only once
        in their source data.
        """
        return {key for key, val in self.identifiers.items() if len(val) == 1}

    def _get_repeats(self) -> set[str]:
        """Returns a set of id keys (inventory numbers) which occur more than once
        in their source data.
        """
        return {key for key, val in self.identifiers.items() if len(val) > 1}

    def print_summary_counts(self) -> None:
        """Prints various counts about the object's identifiers."""
        total_count = sum([len(val) for val in self.identifiers.values()])
        distinct_count = len(self.identifiers)
        singleton_count = len(self.singletons)
        repeat_count = len(self.repeats)
        # self.identifiers is a defaultdict, so be careful querying it;
        # len(self.identifiers[""]) adds an entry, if "" is not already a key!
        if "" in self.identifiers:
            empty_count = len(self.identifiers[""])
        else:
            empty_count = 0
        print(
            f"Counts for {self.source_system} inventory numbers: "
            f"{total_count} total, {distinct_count} distinct, "
            f"{repeat_count} repeats, {singleton_count} singletons, {empty_count} empty."
        )


@dataclass
class ReportRow:
    """Class representing one consistent row of data, which will eventually
    be written to an Excel sheet.
    """

    inventory_number: str
    original_value: str = None
    # Columns of identifiers for both sources will be included in all sheets
    # for consistency, but sometimes will not have data.
    alma_identifiers: list[str] = field(default_factory=list)
    filemaker_identifiers: list[str] = field(default_factory=list)

    @property
    def alma_count(self) -> int:
        return len(self.alma_identifiers)

    @property
    def filemaker_count(self) -> int:
        return len(self.filemaker_identifiers)

    @property
    def total_count(self) -> int:
        return self.alma_count + self.filemaker_count

    @property
    def alma_delimited(self) -> str:
        return ", ".join(self.alma_identifiers)

    @property
    def filemaker_delimited(self) -> str:
        return ", ".join(self.filemaker_identifiers)

    # Allow use in a set by implementing __eq__ and __hash__
    def __eq__(self, other):
        if not isinstance(other, ReportRow):
            return NotImplemented
        return self.inventory_number == other.inventory_number

    def __hash__(self):
        return hash(self.inventory_number)


#######################################
# End of classes, start of main program
#######################################


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
    parser.add_argument(
        "--output_file",
        help="Path to XLSX output file which will be written to",
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

    # Use defaultdict for convenience adding / referencing keys.
    alma_identifiers: id_dict = defaultdict(list)
    for row in data:
        # Many Alma values have spaces; remove them.
        inventory_no = row["Permanent Call Number"].replace(" ", "")
        alma_identifiers[inventory_no].append(row["Holding Id"])

    alma_data = InventoryNumberData(
        source_system="Alma",
        identifier_label="Holdings IDs",
        identifiers=alma_identifiers,
    )
    alma_data.print_summary_counts()
    return alma_data


def _get_filemaker_data(filename: str) -> InventoryNumberData:
    """Returns an InventoryNumberData object with data keyed on the
    normalized Filemaker inventory number, along with a list of the
    Filemaker record id(s) associated with that key.
    """
    with open(filename, "r") as f:
        data = json.load(f)

    # Use defaultdict for convenience adding / referencing keys.
    filemaker_identifiers: id_dict = defaultdict(list)
    for row in data:
        # Some Filemaker inventory numbers end with (or in 1 case, contain)
        # u'\xa0', non-breaking space.  Almost certainly errors; remove this character.
        inventory_no = row["inventory_no"].replace("\xa0", "")
        # inventory_id is an int, in the source json; convert to string.
        filemaker_identifiers[inventory_no].append(str(row["inventory_id"]))

    filemaker_data = InventoryNumberData(
        source_system="Filemaker",
        identifier_label="Record IDs",
        identifiers=filemaker_identifiers,
    )
    filemaker_data.print_summary_counts()
    return filemaker_data


def _get_google_data(filename: str) -> set[str]:
    """Returns a set of non-blank values for inventory numbers."""
    # The target sheet and column are hard-coded here;
    # might want to make them arguments later.
    sheet_name = "Tapes(row 4560-24712)"
    column_name = "Inventory Number [EXTRACTED]"

    df = pd.read_excel(filename, sheet_name=sheet_name, dtype="string")
    total_count = len(df)
    # Drop any rows where the inventory number is missing.
    df.dropna(subset=column_name, inplace=True)
    value_count = len(df)
    empty_count = total_count - value_count

    # Create a set with all raw inventory number values
    unique_values = {row[column_name] for _, row in df.iterrows()}
    unique_count = len(unique_values)
    # Print summary, similar to InventoryNumberData.print_summary_counts().
    multiple_value_count = len([v for v in unique_values if "|" in v])
    single_value_count = unique_count - multiple_value_count
    print(
        f"Counts for Google Sheet inventory numbers: "
        f"{total_count} total, {unique_count} distinct, "
        f"{single_value_count} single values, {multiple_value_count} multiple values, "
        f"{empty_count} empty."
    )

    return unique_values


def _create_dataframe_from_reportrows(data: list[ReportRow]) -> pd.DataFrame:
    """Converts a list of ReportRow objects to a pandas dataframe."""

    # Sort the list of objects on inventory number; not precise, but good enough
    # for these reports.
    data.sort(key=lambda x: x.inventory_number)

    # Convert the sorted input list to a list of lists, which is easier than looping
    # over the input list and adding rows one at a time to a dataframe.
    list_of_lists = [
        [
            record.inventory_number,
            record.original_value,
            record.alma_delimited,
            record.filemaker_delimited,
        ]
        for record in data
    ]

    # Column names are hard-coded as the data will always be the same here.
    column_names = [
        "Inventory Number",
        "Original Value",
        "Alma Holdings IDs",
        "Filemaker Inventory IDs",
    ]

    # Create the dataframe
    df = pd.DataFrame(data=list_of_lists, columns=column_names)
    return df


def _get_one_to_many_matches(
    inventory_number: str,
    alma_data: InventoryNumberData,
    filemaker_data: InventoryNumberData,
    original_value: str = None,
) -> ReportRow:
    """Returns a ReportRow object with the Alma and Filemaker identifiers
    matching the given inventory number.
    """
    alma_identifiers = alma_data.identifiers.get(inventory_number, [])
    filemaker_identifiers = filemaker_data.identifiers.get(inventory_number, [])
    return ReportRow(
        inventory_number=inventory_number,
        alma_identifiers=alma_identifiers,
        filemaker_identifiers=filemaker_identifiers,
        original_value=original_value,
    )


def _get_many_to_many_matches(
    compound_value: str,
    alma_data: InventoryNumberData,
    filemaker_data: InventoryNumberData,
) -> list[ReportRow]:
    """Returns a list of ReportRow objects with the Alma and Filemaker identifiers
    matching the inventory numbers extracted from the pipe-delimited compound value,
    like "M12345|DVD54321".
    """
    all_matches = []
    # Split the compound value into separate inventory numbers, each to be checked.
    for inventory_number in compound_value.split("|"):
        match = _get_one_to_many_matches(
            inventory_number, alma_data, filemaker_data, original_value=compound_value
        )
        all_matches.append(match)

    return all_matches


def report_single_values(
    google_single_values: set[str],
    alma_data: InventoryNumberData,
    filemaker_data: InventoryNumberData,
    report_filename: str,
) -> None:
    """Generates several lists of data for reporting on how single Google values
    are associated with data from Alma and/or Filemaker. These lists are then written
    to an Excel file, each on a different sheet.
    """

    # Initialize all the lists to be built.
    # 1) Matches multiple FM, no Alma (A0 FM)
    multiple_fm_no_alma = []
    # 2) Matches multiple Alma, no FM (AM F0)
    multiple_alma_no_fm = []
    # 3) Matches multiple FM and one Alma (A1 FM)
    multiple_fm_one_alma = []
    # 4) Matches multiple Alma and one FM (AM F1)
    multiple_alma_one_fm = []
    # 5) Matches multiple FM and multiple Alma (AM FM) (separate from the prev 2, to avoid overlaps)
    multiple_fm_multiple_alma = []
    # 6) Matches no FM, no Alma (A0 F0) (not requested, but seems useful to know...)
    no_fm_no_alma = []
    # Leftovers not matches by a case above
    leftovers = []

    for inventory_number in google_single_values:
        matches = _get_one_to_many_matches(inventory_number, alma_data, filemaker_data)
        if matches.filemaker_count > 1 and matches.alma_count == 0:
            multiple_fm_no_alma.append(matches)
        elif matches.alma_count > 1 and matches.filemaker_count == 0:
            multiple_alma_no_fm.append(matches)
        elif matches.filemaker_count > 1 and matches.alma_count == 1:
            multiple_fm_one_alma.append(matches)
        elif matches.alma_count > 1 and matches.filemaker_count == 1:
            multiple_alma_one_fm.append(matches)
        elif matches.filemaker_count > 1 and matches.alma_count > 1:
            multiple_fm_multiple_alma.append(matches)
        elif matches.filemaker_count == 0 and matches.alma_count == 0:
            no_fm_no_alma.append(matches)
        else:
            # Not a reportable case, but capture for possible use / debugging.
            leftovers.append(matches)

    # Quick counts
    print(f"{len(multiple_fm_no_alma)=}")
    print(f"{len(multiple_alma_no_fm)=}")
    print(f"{len(multiple_fm_one_alma)=}")
    print(f"{len(multiple_alma_one_fm)=}")
    print(f"{len(multiple_fm_multiple_alma)=}")
    print(f"{len(no_fm_no_alma)=}")
    print(f"{len(leftovers)=}")

    # Convert each list of objects to a dataframe and export to Excel.
    # 1
    write_excel_sheet(
        filename=report_filename,
        sheet_name="S1) Single G Mult FM No Alma",
        data=multiple_fm_no_alma,
    )

    # 2
    write_excel_sheet(
        filename=report_filename,
        sheet_name="S2) Single G Mult Alma No FM",
        data=multiple_alma_no_fm,
    )

    # 3
    write_excel_sheet(
        filename=report_filename,
        sheet_name="S3) Single G Mult FM One Alma",
        data=multiple_fm_one_alma,
    )

    # 4
    write_excel_sheet(
        filename=report_filename,
        sheet_name="S4) Single G Mult Alma One FM",
        data=multiple_alma_one_fm,
    )

    # 5
    write_excel_sheet(
        filename=report_filename,
        sheet_name="S5) Single G Mult FM Mult Alma",
        data=multiple_fm_multiple_alma,
    )

    # 6
    write_excel_sheet(
        filename=report_filename,
        sheet_name="S6) Single G No FM No Alma",
        data=no_fm_no_alma,
    )


def report_multiple_values(
    google_multiple_values: set[str],
    alma_data: InventoryNumberData,
    filemaker_data: InventoryNumberData,
    report_filename: str,
) -> None:
    """Generates several lists of data for reporting on how multiple Google values
    (a pipe-delimited string representing the original value in a single Google cell)
    are associated with data from Alma and/or Filemaker.
    These lists are then written to an Excel file, each on a different sheet.
    """
    # Initialize all the lists to be built.
    # 1) Multiple inventory numbers in a single Google Sheet row,
    # where each individual inventory number matches to only one record (in FM or Alma).
    each_to_one_fm_or_alma = []
    # 2) Multiple inventory numbers in a single Google Sheet row,
    # where at least one inventory number matches to multiple records (in FM and/or Alma).
    at_least_one_to_mult_fm_or_alma = []
    # Leftovers not matches by a case above
    leftovers = []

    for compound_value in google_multiple_values:
        matches = _get_many_to_many_matches(compound_value, alma_data, filemaker_data)
        # Case 1: Does each inventory number match only one record (in FM or Alma)?
        if all([match.total_count == 1 for match in matches]):
            # Add all of the matches for reporting.
            each_to_one_fm_or_alma.extend(matches)
        # Case 2: Does at least one inventory number match multiple records (in FM and/or Alma)?
        elif any(
            [(match.alma_count > 1 or match.filemaker_count > 1) for match in matches]
        ):
            # Add only the qualifying matches for reporting.
            # The test is repeated, but this is quick enough and I don't see a better way...
            for match in matches:
                if match.alma_count > 1 or match.filemaker_count > 1:
                    at_least_one_to_mult_fm_or_alma.append(match)
        else:
            # Not a reportable case, but capture for possible use / debugging.
            leftovers.extend(matches)

    # Quick counts: with duplicates
    print("Multi-match counts before de-duping")
    print(f"{len(each_to_one_fm_or_alma)=}")
    print(f"{len(at_least_one_to_mult_fm_or_alma)=}")
    print(f"{len(leftovers)=}")
    # De-duplicate these
    each_to_one_fm_or_alma = list(set(each_to_one_fm_or_alma))
    at_least_one_to_mult_fm_or_alma = list(set(at_least_one_to_mult_fm_or_alma))
    leftovers = list(set(leftovers))
    # Quick counts: without duplicates
    print("Multi-match counts after de-duping")
    print(f"{len(each_to_one_fm_or_alma)=}")
    print(f"{len(at_least_one_to_mult_fm_or_alma)=}")
    print(f"{len(leftovers)=}")

    # Convert each list of objects to a dataframe and export to Excel.
    # 1
    write_excel_sheet(
        filename=report_filename,
        sheet_name="M1) Many to one",
        data=each_to_one_fm_or_alma,
    )

    # 2
    write_excel_sheet(
        filename=report_filename,
        sheet_name="M2) Many to many",
        data=at_least_one_to_mult_fm_or_alma,
    )


def write_excel_sheet(filename: str, sheet_name: str, data: list[ReportRow]) -> None:
    """Creates an Excel file with the given name, or updates an existing one, with one
    sheet containing the input data.
    For existing files, if a sheet with sheet_name already exists, that sheet will be replaced;
    otherwise, a new sheet will be created within the existing file.
    """
    df = _create_dataframe_from_reportrows(data)
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
    report_filename = args.output_file

    alma_data = _get_alma_data(args.alma_file)
    filemaker_data = _get_filemaker_data(args.filemaker_data_file)
    google_data = _get_google_data(args.google_file)

    # All matches are done from Google to other source(s).
    # This contains both single-value strings, (e.g., "M123", "DVD999"), as well as
    # multiple-value pipe-delimited strings, (e.g., "M456|M789", "XFE111|XFE222|XFE333").
    # For each value: if it's a single, process as is; if multiple, split and process
    # via different matches.
    google_single_values = {value for value in google_data if "|" not in value}
    google_multiple_values = google_data - google_single_values

    report_single_values(
        google_single_values, alma_data, filemaker_data, report_filename
    )
    report_multiple_values(
        google_multiple_values, alma_data, filemaker_data, report_filename
    )


if __name__ == "__main__":
    main()
