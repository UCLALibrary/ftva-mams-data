import argparse
import csv
import json
import pandas as pd
from collections import Counter


def _get_alma_data(filename: str) -> dict:
    """Reads Alma holdings data from the given CSV file. This function returns
    only information about records which occur just once in the file, based on
    inventory number.

    :param filename: Path to the CSV file with Alma holdings data.
    :returns alma_data: A dictionary keyed on inventory number, with the full
    row of data as the value.
    """
    with open(filename, "r") as f:
        data = csv.DictReader(f)
        data = [row for row in data]
    print(f"Read {len(data)} records from {filename}")

    # Clean up & normalize Alma-specific inventory numbers.
    for row in data:
        # Many Alma values have spaces; remove them;
        # also force to upper case.
        row["inventory_number"] = row["Permanent Call Number"].replace(" ", "").upper()

    singletons = _get_singletons(data)

    # Get the data just for rows which have a unique inventory number.
    alma_data = {
        row["inventory_number"]: row
        for row in data
        if row["inventory_number"] in singletons
    }

    return alma_data


def _get_dl_data(filename: str) -> dict:
    """Reads Digital Labs data from the given JSON file. This function returns
    only information about records which occur just once in the file, based on
    inventory number.

    :param filename: Path to the JSON file with Digital Labs data.
    :returns dl_data: A dictionary keyed on inventory number, with the full
    row of data as the value.
    """
    with open(filename, "r") as f:
        data: list[dict] = json.load(f)
    print(f"Read {len(data)} records from {filename}")

    # DL data exported as a Django fixture has model (ignored here), pk (id),
    # and fields (dict of all other field names and values).
    # Combine these for later use.
    field_data: list[dict] = []
    for row in data:
        tmp_data: dict = row["fields"]
        tmp_data["pk"] = row["pk"]
        field_data.append(tmp_data)

    singletons = _get_singletons(field_data)

    # Get the data just for rows which have a unique inventory number.
    dl_data = {
        row["inventory_number"]: row
        for row in field_data
        if row["inventory_number"] in singletons
    }

    return dl_data


def _get_filemaker_data(filename: str) -> dict:
    """Reads Filemaker data from the given JSON file. This function returns
    only information about records which occur just once in the file, based on
    inventory number.

    :param filename: Path to the JSON file with Alma holdings data.
    :returns filemaker_data: A dictionary keyed on inventory number, with the full
    row of data as the value.
    """
    with open(filename, "r") as f:
        data: list[dict] = json.load(f)
    print(f"Read {len(data)} records from {filename}")

    # Clean up & normalize Filemaker-specific inventory numbers.
    for row in data:
        # Some Filemaker inventory numbers end with (or contain)
        # u'\xa0', non-breaking space.  Almost certainly errors; remove this character.
        # Also force to upper case, and rename to inventory_number for consistency
        # with other data sources.
        row["inventory_number"] = row.pop("inventory_no").replace("\xa0", "").upper()

    singletons = _get_singletons(data)

    # Get the data just for rows which have a unique inventory number.
    filemaker_data = {
        row["inventory_number"]: row
        for row in data
        if row["inventory_number"] in singletons
    }

    return filemaker_data


def _get_singletons(data: list[dict]) -> set[str]:
    # Get number of times each inventory number occurs.
    counts = Counter([row["inventory_number"] for row in data])
    # Uniqueness guaranteed by count == 1, but use set for much faster lookups in next step.
    singletons = {
        inventory_number for inventory_number, count in counts.items() if count == 1
    }
    return singletons


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alma_data_file",
        help="Path to CSV file containing FTVA Alma holdings data",
        required=True,
    )
    parser.add_argument(
        "--dl_data_file",
        help="Path to JSON file containing FTVA Digital Labs (formerly Google Sheets) data",
        required=True,
    )
    parser.add_argument(
        "--filemaker_data_file",
        help="Path to JSON file containing FTVA Filemaker data",
        required=True,
    )
    parser.add_argument(
        "--output_file",
        help="Path to XLSX output file which will be written to",
        required=True,
    )
    args = parser.parse_args()
    return args


def main() -> None:
    args = _get_args()

    alma_data = _get_alma_data(args.alma_data_file)
    print(f"Alma singletons: {len(alma_data)} rows")

    dl_data = _get_dl_data(args.dl_data_file)
    print(f"DL singletons: {len(dl_data)} rows")

    filemaker_data = _get_filemaker_data(args.filemaker_data_file)
    print(f"FM singletons: {len(filemaker_data)} rows")

    # We only want the "perfect" matches, where the inventory number
    # occurs in all dictionaries.
    # Convert keys to sets and find the intersection;
    # sort the combined set of keys for better output later.
    perfect_matches = sorted(set(dl_data) & set(alma_data) & set(filemaker_data))
    print(f"Found {len(perfect_matches)} perfect matches.")

    # Get selected data from the sources for each matched inventory number.
    output_data = []
    for inventory_number in perfect_matches:
        merged_data = {
            "inventory_number": inventory_number,
            "alma_holdings_id": alma_data[inventory_number].get("Holding Id", ""),
            "fm_inventory_id": filemaker_data[inventory_number].get("inventory_id", ""),
            "dl_record_id": dl_data[inventory_number].get("pk", ""),
            "fm_title": filemaker_data[inventory_number].get("title", ""),
            "dl_carrier_a": dl_data[inventory_number].get("carrier_a", ""),
            "dl_carrier_a_loc": dl_data[inventory_number].get("carrier_a_location", ""),
            "dl_carrier_b": dl_data[inventory_number].get("carrier_b", ""),
            "dl_carrier_b_loc": dl_data[inventory_number].get("carrier_b_location", ""),
            "dl_hard_drive_name": dl_data[inventory_number].get("hard_drive_name", ""),
            "dl_file_folder_name": dl_data[inventory_number].get(
                "file_folder_name", ""
            ),
            "dl_sub_folder_name": dl_data[inventory_number].get("sub_folder_name", ""),
            "dl_file_name": dl_data[inventory_number].get("file_name", ""),
        }
        output_data.append(merged_data)

    # Turn the list of dictionaries into a DataFrame and write it to Excel file.
    df = pd.DataFrame(output_data)
    with pd.ExcelWriter(args.output_file) as writer:
        df.to_excel(writer, index=False)


if __name__ == "__main__":
    main()
