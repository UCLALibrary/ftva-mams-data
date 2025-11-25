import argparse
import logging
import csv
import tomllib
from alma_api_client import AlmaAPIClient, APIError
from datetime import datetime
from pathlib import Path


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


def get_inventory_nos_to_update(alma_data: list[dict]) -> list[dict]:
    """Extracts inventory numbers with Permanent Call Numbers that:
        - contain a space character in the second-to-last position
        - have last character "T", "M", or "R"
        - do not contain a hyphen or the word "and"
    These Permanent Call Numbers will be updated by removing the space character.

    :param alma_data: List of dictionaries containing Alma data with Permanent Call Numbers.
    :return: List of dictionaries of alma_data records, with new `new_permanent_call_number`
            field added for each record to be updated.
    """
    inventory_nos_to_update = []
    for record in alma_data:
        permanent_call_number = record.get("Permanent Call Number", "")
        if len(permanent_call_number) < 2:
            continue
        if (
            permanent_call_number[-2] == " "
            and permanent_call_number[-1] in {"T", "M", "R"}
            and "-" not in permanent_call_number
            and "and" not in permanent_call_number.lower()
        ):
            record["new_permanent_call_number"] = (
                permanent_call_number[:-2] + permanent_call_number[-1]
            )
            inventory_nos_to_update.append(record)
    return inventory_nos_to_update


def _read_alma_data(alma_data_file: str) -> list[dict]:
    """Reads Alma data from a CSV file.

    :param alma_data_file: Path to the CSV file containing Alma data.
    :return: List of dictionaries representing the Alma data.
    """
    with open(alma_data_file, mode="r", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        alma_data = [row for row in reader]
    return alma_data


def main():
    """Main function to remove FTVA inventory without spaces in Permanent Call Numbers."""
    args = _get_arguments()
    config = _get_config(args.config_file)
    _configure_logging()

    if args.environment == "production":
        alma_api_key = config["alma_config"]["alma_api_key"]
    else:  # sandbox
        alma_api_key = config["alma_config"]["sandbox_alma_api_key"]

    alma_client = AlmaAPIClient(api_key=alma_api_key)
    logging.info(
        f"Starting FTVA inventory Permanent Call Number update process in {args.environment}."
    )

    if args.environment == "sandbox":
        logging.info("Sandbox environment selected; test data will be used.")
        logging.info(
            "Test data contains five records from sandbox Alma, three of which require an update."
        )
        alma_data = [
            # Record that requires update
            {
                "MMS Id": "99688013506533",
                "Holdings ID": "22541990160006533",
                "Permanent Call Number": "FE1605 T",
            },
            # 2nd record that requires update
            {
                "MMS Id": "99439703506533",
                "Holdings ID": "22541990530006533",
                "Permanent Call Number": "VA19633 M",
            },
            # 3rd record that requires update
            {
                "MMS Id": "99548133506533",
                "Holdings ID": "22547024400006533",
                "Permanent Call Number": "XFE1014 M",
            },
            # Record that does not require update (no space)
            {
                "MMS Id": "9976843506533",
                "Holdings ID": "22541990130006533",
                "Permanent Call Number": "M28479",
            },
            # Record that does not require update (contains hyphen)
            {
                "MMS Id": "99203173506533",
                "Holdings ID": "22542000310006533",
                "Permanent Call Number": "VA11724 -725 T",
            },
        ]
    else:  # production
        alma_data = _read_alma_data(args.alma_data_file)

    inventory_nos_to_update = get_inventory_nos_to_update(alma_data)
    logging.info(f"Found {len(inventory_nos_to_update)} inventory records to update.")

    for record in inventory_nos_to_update:
        mms_id = record["MMS Id"]
        holding_id = record["Holdings ID"]
        new_permanent_call_number = record["new_permanent_call_number"]

        try:
            holding_record = alma_client.get_holding_record(mms_id, holding_id)
            marc_record = holding_record.marc_record
            # Update the Permanent Call Number (FTVA) subfield (852 $h)

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

            for field_852 in fields_852:
                subfield_h = field_852.get_subfields("h")
                if subfield_h:
                    field_852.delete_subfield("h")
                    field_852.add_subfield("h", new_permanent_call_number)
                    logging.info(
                        f"Update identified for MMS ID {mms_id}, holding {holding_id}: "
                        f"Permanent Call Number change from {record['Permanent Call Number']} "
                        f"to {new_permanent_call_number}."
                    )
            if args.dry_run:
                logging.info(
                    f"Dry run enabled; not updating MMS ID {mms_id}, holding {holding_id} in Alma."
                )
                continue

            # Update the MARC record of the original HoldingRecord object
            holding_record.marc_record = marc_record
            # Send the updated holding record back to Alma
            alma_client.update_holding_record(mms_id, holding_record)
            logging.info(
                f"Successfully updated MMS ID {mms_id}, holding {holding_id} in Alma."
            )

        except APIError as e:
            logging.error(
                f"API error while processing MMS ID {mms_id}, holding {holding_id}: {e}"
            )

    logging.info("FTVA inventory number update process completed.")


if __name__ == "__main__":
    main()
