import argparse
import json
import tomllib
import logging
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file",
        help="Path to config file with Digital Data connection info",
        required=True,
    )
    parser.add_argument(
        "--offset",
        type=int,
        help="Offset of records at which to start fetching, for pagination",
        required=False,
        default=0,
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Number of records to fetch in each batch, for pagination",
        required=False,
        default=1000,
    )
    args = parser.parse_args()
    return args


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: The path to the config file.
    :return: A dictionary containing the configuration.
    """
    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _configure_logger(name: str | None = None):
    """Returns a logger for the current application.
    A unique log filename is created using the current time, and log messages
    will use the name in the 'logger' field.

    :param name: Optional name for the logger. If not provided, uses the base filename
    of the current script.
    :return: Configured logger instance."""

    if not name:
        # Use base filename of current script.
        name = Path(__file__).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging_file = Path("logs", f"{name}_{timestamp}.log")  # Log to `logs/` dir
    logging_file.parent.mkdir(parents=True, exist_ok=True)  # Make `logs/` dir, if none
    logging.basicConfig(
        filename=logging_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )


def _write_json(data: list[dict], filename_base: str = "digital_data"):
    """Write data to a JSON file.

    :param data: The data to write to the file.
    :param filename_base: The base name of the file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_base}_{timestamp}.json"
    logging.info(f"WRITING DATA TO {filename}")
    with open(filename, "w") as f:
        json.dump(data, f)


def main() -> None:
    """Get all records from the Digital Data Django application,
    using the `records/` API endpoint.
    """
    args = _get_args()
    config = _get_config(args.config_file)
    _configure_logger()

    digital_data_base_url = "https://digital-data.cinema.ucla.edu/"
    digital_data_api_endpoint = "records/"
    url = urljoin(digital_data_base_url, digital_data_api_endpoint)

    session = requests.Session()
    session.auth = (
        config["digital_data"]["user"],
        config["digital_data"]["password"],
    )

    offset = args.offset
    limit = args.limit

    print(
        "Retrieving all records from the Digital Data API...\n"
        "see `logs/` for more details."
    )
    all_records = []
    initial_iteration = True  # used for printing total records during first iteration
    while True:  # break out of loop when no more records to fetch
        try:
            response = session.get(url, params={"offset": offset, "limit": limit})
            response.raise_for_status()
            if initial_iteration:  # print total_records from first response only
                total_records = response.json()["total_records"]
                logging.info(f"START: {datetime.now()}")
                logging.info(f"TOTAL RECORDS: {total_records}")
                initial_iteration = False
            logging.info(f"Getting {limit} records starting at {offset}...")
            records = response.json()["records"]  # list of records in batch
            all_records.extend(records)
            offset += limit
            # Break out of loop for last batch of records
            if len(records) < limit:
                break
        except requests.exceptions.RequestException as e:
            logging.error(
                f"Error getting records at offset {offset} from the Digital Data API: {e}"
            )
            break

    logging.info(f"RECORDS RETRIEVED: {len(all_records)}")
    _write_json(all_records, "digital_data")
    logging.info(f"DONE: {datetime.now()}")


if __name__ == "__main__":
    main()
