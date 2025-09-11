import csv
import json
import argparse
import tomllib
import logging
from datetime import datetime
from pathlib import Path
from ftva_etl import (
    AlmaSRUClient,
    FilemakerClient,
    DigitalDataClient,
    get_mams_metadata,
)
from requests.exceptions import HTTPError


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments for config_file, input_file, and
    output_file as a Namespace object."""
    parser = argparse.ArgumentParser(description="Process metadata for MAMS ingestion.")
    parser.add_argument(
        "--config_file",
        help="Path to configuration file with API credentials.",
        required=True,
    )
    parser.add_argument(
        "--input_file",
        type=str,
        required=True,
        help="Path to the input CSV file containing records to be processed.",
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="output/",
        required=False,
        help="Path to the output directory where JSON files will be saved. Defaults to 'output/'.",
    )
    return parser.parse_args()


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary."""

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _get_logger(name: str | None = None) -> logging.Logger:
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
    logger = logging.getLogger(name)
    logging.basicConfig(
        filename=logging_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    return logger


def _read_input_file(file_path: str) -> list[dict]:
    """Read the input CSV file and return a list of dictionaries.

    :param file_path: Path to the input CSV file.
    :return: List of dictionaries representing each row in the CSV file."""
    with open(file_path, mode="r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return [row for row in reader]


def _write_output_file(output_file: str | Path, data: list[dict]) -> None:
    """Write processed data to a JSON file.

    :param output_file: Path to the output JSON file.
    :param data: List of dicts containing processed metadata."""
    output_path = Path(output_file)
    # Create parent directories if they don't exist.
    # Allows for `output_file` to be a relative path.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, mode="w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def _initialize_clients(
    config: dict,
) -> tuple[AlmaSRUClient, FilemakerClient, DigitalDataClient]:
    """Initialize the clients for the program.

    :param config: The program's configuration dict.
    :return: A tuple of the initialized clients."""
    return (
        AlmaSRUClient(),
        FilemakerClient(config["filemaker"]["user"], config["filemaker"]["password"]),
        DigitalDataClient(
            config["digital_data"]["user"],
            config["digital_data"]["password"],
            config["digital_data"]["url"],
        ),
    )


def _process_input_data(
    input_data: list[dict],
    alma_sru_client: AlmaSRUClient,
    filemaker_client: FilemakerClient,
    digital_data_client: DigitalDataClient,
) -> tuple[list[dict], int, int]:
    """Process input data and return a list of metadata records, plus counts of assets and tracks.

    :param input_data: The input data to process.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :param filemaker_client: The FilemakerClient instance to use to get the FM record.
    :param digital_data_client: The DigitalDataClient instance to use to get the DD record.
    :return: A tuple of the list of metadata records, the count of assets, and the count of tracks."""
    metadata_records = []
    asset_count = 0
    track_count = 0
    for row in input_data:
        # Adding `try/except` block to prevent the program from crashing if a record
        # is not found. This would happen if the dev and prod databases are out of sync.
        try:
            digital_data_record = digital_data_client.get_record_by_id(
                row["dl_record_id"]
            )
            inventory_number = digital_data_record["inventory_number"]
            bib_record = alma_sru_client.search_by_call_number(inventory_number)[0]
            filemaker_record = filemaker_client.search_by_inventory_number(
                inventory_number
            )[0]
        except HTTPError as error:
            if error.response.status_code == 404:
                logger.error(f"Record {row['dl_record_id']} not found in Digital Data.")
            else:
                logger.error(error)
            continue

        # Initialize to None. Will be set to UUID if record is a track.
        match_asset_uuid = None
        if row["Audio Track?"].lower().strip() == "yes":
            match_asset_uuid = row["match_asset"]
            if not match_asset_uuid:
                logger.error(
                    f"Record {row['dl_record_id']} is marked as a track, "
                    "but no UUID for the match asset is provided."
                )
                continue

        metadata_record = get_mams_metadata(
            bib_record, filemaker_record, digital_data_record, match_asset_uuid
        )

        # If metadata_record has `match_asset` value, it's a track;
        # set `record_type` accordingly.
        if metadata_record.get("match_asset"):
            metadata_record["record_type"] = "track"
            track_count += 1
        else:
            metadata_record["record_type"] = "asset"
            asset_count += 1

        metadata_records.append(metadata_record)
    return metadata_records, asset_count, track_count


def main() -> None:
    args = _get_arguments()
    config = _get_config(args.config_file)

    # Read input file
    logger.info(f"Loading input data from {args.input_file}")
    input_data = _read_input_file(args.input_file)
    logger.info(f"Loaded {len(input_data)} records from input file.")

    alma_sru_client, filemaker_client, digital_data_client = _initialize_clients(config)

    metadata_records, asset_count, track_count = _process_input_data(
        input_data, alma_sru_client, filemaker_client, digital_data_client
    )

    # Save processed data to JSON file named after the input file.
    output_filename_stem = Path(args.input_file).stem
    _write_output_file(
        Path(args.output_dir, f"{output_filename_stem}.json"), metadata_records
    )

    logger.info(f"Processed {track_count} tracks and {asset_count} assets.")
    logger.info(f"Processed data saved to '{args.output_dir}'")


if __name__ == "__main__":
    # Make logger available at module level.
    # Otherwise, it's not available when running tests.
    logger = _get_logger()
    main()
