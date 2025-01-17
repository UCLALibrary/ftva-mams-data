import argparse
import tomllib
import json
from pymarc import Record
from alma_api_client import AlmaAPIClient, get_pymarc_record_from_bib


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file", help="Path to configuration file", required=True
    )

    parser.add_argument(
        "--input_file",
        help="Path to input JSON file containing MMS IDs",
        required=True,
    )
    parser.add_argument(
        "--output_file",
        help="Path to MARC output file which will be written from report data",
        required=True,
    )
    args = parser.parse_args()
    return args


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file."""
    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def get_deduped_mms_ids(input_file: str) -> set[str]:
    """Returns a set of unique MMS IDs from an input JSON file."""
    with open(input_file, "r") as f:
        data = json.load(f)
    mms_ids = set(item["MMS Id"] for item in data)
    return mms_ids


def get_bib_record(client: AlmaAPIClient, mms_id: str) -> Record:
    """Gets a bib record with holding data from Alma API."""
    bib_data = client.get_bib(mms_id).get("content")
    bib_record = get_pymarc_record_from_bib(bib_data)
    return bib_record


def write_records_to_file(records: list[Record], output_file: str) -> None:
    """Writes a list of MARC records to a file."""
    with open(output_file, "wb") as f:
        for record in records:
            f.write(record.as_marc())
    print(f"Output written to {output_file}")


if __name__ == "__main__":
    args = _get_args()
    config = _get_config(args.config_file)
    api_key = config["alma_config"]["alma_api_key"]
    client = AlmaAPIClient(api_key)
    mms_ids = get_deduped_mms_ids(args.input_file)
    print(f"Processing {len(mms_ids)} unique MMS IDs")
    output_records = []
    for mms_id in mms_ids:
        bib_record = get_bib_record(client, mms_id)
        output_records.append(bib_record)
    write_records_to_file(output_records, args.output_file)
