import argparse
import logging
import csv
import tomllib
from alma_api_client import AlmaAPIClient, APIError
from datetime import datetime
from pathlib import Path
from pymarc import Field


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments as a Namespace object.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--environment",
        choices=["sandbox", "production"],
        required=True,
        help="Alma environment (sandbox or production)",
    )
    parser.add_argument(
        "--config_file",
        type=str,
        default="secret_config.toml",
        help="Path to TOML config file with API keys",
    )
    parser.add_argument(
        "--alma_data_file",
        type=str,
        help="Path to CSV file with Alma data, as produced by get_ftva_holdings_report.py",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="If set, no changes will be made to Alma; only log what would be done",
    )
    return parser.parse_args()


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary.
    """

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _configure_logging():
    """Returns a logger for the current application.
    A unique log filename is created using the current time, and log messages
    will use the name in the 'logger' field.

    :return: Configured logger.
    """
    name = Path(__file__).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging_file = Path("logs", f"{name}_{timestamp}.log")  # Log to `logs/` dir
    logging_file.parent.mkdir(parents=True, exist_ok=True)  # Make `logs/` dir, if none
    logging.basicConfig(
        filename=logging_file,
        level="INFO",
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    # always suppress urllib3 logs with lower level than WARNING
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _read_alma_data(alma_data_file: str) -> list[dict]:
    """Reads Alma data from a CSV file.

    :param alma_data_file: Path to the CSV file containing Alma data.
    :return: List of dictionaries representing the Alma data.
    """
    with open(alma_data_file, mode="r", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        alma_data = [row for row in reader]
    return alma_data


def get_subfield_position(field: Field, subfield_code: str) -> int | None:
    """Return 0-based position of the first subfield with the given code,
    or None if not found.

    :param field: The Pymarc Field to search.
    :param subfield_code: The subfield code to search for.
    :return: The 0-based position of the first subfield with the given code,
        or None if not found.
    """
    found = False
    pos = -1

    for subfield in field:
        pos += 1
        if subfield.code == subfield_code:
            found = True
            break
    return pos if found else None


def get_updated_call_number(call_number: str) -> str:
    """Returns an updated 852 $h value. Call numbers needing updates meet the following criteria:
        - space character in the second-to-last position
        - last character "T", "M", or "R"
        - no hyphen or the word "and"

    If the call number meets these criteria, the space is removed.
    If the call number does not meet these criteria, it is returned unchanged.

    :param call_number: Original inventory number (852 $h)
    :return: Updated inventory number with space removed, or the original if no update needed.
    """

    if (
        len(call_number) >= 2
        and call_number[-2] == " "
        and call_number[-1] in {"T", "M", "R"}
        and "-" not in call_number
        and "and" not in call_number.lower()
    ):
        return call_number[:-2] + call_number[-1]
    return call_number


def main():
    args = _get_arguments()
    config = _get_config(args.config_file)
    _configure_logging()

    if args.environment == "production":
        alma_api_key = config["alma_config"]["alma_api_key"]
    else:  # sandbox
        alma_api_key = config["alma_config"]["sandbox_alma_api_key"]

    alma_client = AlmaAPIClient(api_key=alma_api_key)
    logging.info(
        f"Starting FTVA inventory number update process in {args.environment}."
    )

    alma_data = _read_alma_data(args.alma_data_file)

    logging.info(f"Found {len(alma_data)} records to check for updates.")

    # Itnitialize counter for updated records
    updated_record_count = 0

    for record in alma_data:
        mms_id = record["MMS Id"]
        holding_id = record["Holdings ID"]

        try:
            holding_record = alma_client.get_holding_record(mms_id, holding_id)
            marc_record = holding_record.marc_record

            if marc_record is None:
                logging.warning(
                    f"No MARC record found for MMS ID {mms_id}, holding {holding_id}; skipping"
                )
                continue

            fields_852 = marc_record.get_fields("852")
            if not fields_852:
                logging.info(
                    f"No 852 field found for MMS ID {mms_id}, holding {holding_id}; skipping"
                )
                continue

            # Get the current 852 $h value (not repeatable, so take the first one)
            try:
                current_inv_no = fields_852[0].get_subfields("h")[0]
            except IndexError:
                logging.info(
                    f"No 852 $h subfield found for MMS ID {mms_id}, holding {holding_id}; skipping"
                )
                continue
            new_inv_no = get_updated_call_number(current_inv_no)
            if new_inv_no == current_inv_no:
                logging.info(
                    f"No update needed for MMS ID {mms_id}, holding {holding_id}"
                    f" ('{current_inv_no}'); skipping"
                )
                continue

            # Update the 852 $h value
            h_pos = get_subfield_position(fields_852[0], "h")
            fields_852[0].delete_subfield("h")
            fields_852[0].add_subfield("h", new_inv_no, pos=h_pos)
            logging.info(
                f"Updated MMS ID {mms_id}, holding {holding_id}: "
                f"'{current_inv_no}' -> '{new_inv_no}'"
            )

            if args.dry_run:
                logging.info(
                    f"Dry run enabled; not updating MMS ID {mms_id}, holding {holding_id} in Alma."
                )
                updated_record_count += 1
                continue

            # Update the MARC record of the original HoldingRecord object
            holding_record.marc_record = marc_record
            # Send the updated holding record back to Alma
            alma_client.update_holding_record(mms_id, holding_record)
            logging.info(
                f"Successfully updated MMS ID {mms_id}, holding {holding_id} in Alma."
            )
            updated_record_count += 1

        except APIError as e:
            logging.error(
                f"API error while processing MMS ID {mms_id}, holding {holding_id}: {e}"
            )

    logging.info(
        f"FTVA inventory number update process completed. Updated {updated_record_count} records."
    )


if __name__ == "__main__":
    main()
