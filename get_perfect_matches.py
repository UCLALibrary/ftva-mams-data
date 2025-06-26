import argparse
import csv
import json
import pandas as pd


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

    alma_data = {}
    for row in data:
        # Many Alma values have spaces; remove them;
        # also force to upper case.
        inventory_no: str = row["Permanent Call Number"].replace(" ", "").upper()
        # Keep only unique (after normalizing) inventory numbers, and their
        # full row of data for use later.
        if inventory_no not in alma_data:
            alma_data[inventory_no] = row

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
        data = json.load(f)
    print(f"Read {len(data)} records from {filename}")

    dl_data = {}
    for row in data:
        # DL data exported as a Django fixture has model (ignored here), pk (id),
        # and fields (dict of all other field names and values).
        # Combine these for later use.
        field_data = row["fields"]
        field_data["pk"] = row["pk"]
        # DL inventory numbers were previously normalized at the source;
        # we don't care if they're compound or invalid, as those won't match
        # Alma or Filemaker data anyhow.
        inventory_no: str = field_data["inventory_number"]
        # Keep only unique (after normalizing) inventory numbers, and their
        # full row of data for use later.
        if inventory_no not in dl_data:
            dl_data[inventory_no] = field_data

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
        data = json.load(f)
    print(f"Read {len(data)} records from {filename}")

    filemaker_data = {}
    for row in data:
        # Some Filemaker inventory numbers end with (or in 1 case, contain)
        # u'\xa0', non-breaking space.  Almost certainly errors; remove this character.
        # Also force to upper case.
        inventory_no: str = row["inventory_no"].replace("\xa0", "").upper()
        # Keep only unique (after normalizing) inventory numbers, and their
        # full row of data for use later.
        if inventory_no not in filemaker_data:
            filemaker_data[inventory_no] = row

    return filemaker_data


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
    print(f"Alma data: {len(alma_data)} rows")

    dl_data = _get_dl_data(args.dl_data_file)
    print(f"DL data: {len(dl_data)} rows")

    filemaker_data = _get_filemaker_data(args.filemaker_data_file)
    print(f"FM data: {len(filemaker_data)} rows")

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
