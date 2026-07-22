import csv
import json
import logging
import tomllib

from datetime import datetime
from pathlib import Path


def validate_match_asset_relationships(
    metadata_records: list[dict],
    check_inventory_numbers: bool = True,
) -> list[str]:
    """For each metadata record with a `match_asset` field, check that:

    1. the match_asset value actually references another record in the batch; and
    2. the first inventory numbers of the two related records are the same
        (if `check_inventory_numbers` is True).

    :param metadata_records: List of metadata records.
    :param check_inventory_numbers: Whether to check that the first inventory numbers
        of the two related records are the same (defaults to True).
    :return: A list of validation problems, if any.
    """
    # Index records by UUID for quick lookup below
    records_by_uuid = {
        record["uuid"]: record for record in metadata_records if record.get("uuid")
    }

    validation_problems = []
    for record in metadata_records:
        # Skip records without a `match_asset` field
        match_asset_uuid = record.get("match_asset")
        if not match_asset_uuid:
            continue

        matched_record = records_by_uuid.get(match_asset_uuid)
        # Append a message if the match_asset is not found in the batch,
        # then move on to the next record
        if not matched_record:
            validation_problems.append(
                f"Match asset {match_asset_uuid} for record {record['uuid']} not found in batch."
            )
            continue

        if check_inventory_numbers:
            # Now check inventory numbers, using the first inv no for each record
            record_inv = (record.get("inventory_numbers") or [None])[0]
            matched_record_inv = (matched_record.get("inventory_numbers") or [None])[0]

            # Append a message if the inventory numbers do not match
            if record_inv != matched_record_inv:
                validation_problems.append(
                    f"Inventory numbers do not match for match_asset relationship: "
                    f"{record['record_type']} {record['uuid']}: '{record_inv}', "
                    f"{matched_record['record_type']} {matched_record['uuid']}: "
                    f"'{matched_record_inv}'"
                )
    return validation_problems


def count_assets_and_tracks(metadata_records: list[dict]) -> tuple[int, int]:
    """Count the number of assets and tracks in the metadata records.

    :param metadata_records: List of metadata records.
    :return: A tuple containing the count of assets and tracks."""
    asset_count = sum(
        1 for record in metadata_records if record.get("record_type") == "asset"
    )
    track_count = sum(
        1 for record in metadata_records if record.get("record_type") == "track"
    )
    return asset_count, track_count


def read_input_file(input_file: str | Path) -> list[dict]:
    """Read the input file and return the data as a list of dictionaries.

    :param input_file: Path to the input CSV file.
    :return: A list of dictionaries."""
    with open(input_file, "r", encoding="utf-8") as file:
        return [row for row in csv.DictReader(file)]


def write_output_file(output_file: str | Path, data: dict | list[dict]) -> None:
    """Write processed data to a JSON file.

    :param output_file: Path to the output JSON file.
    :param data: Dict or list of dicts to write to the output file."""
    output_path = Path(output_file)
    # Create parent directories if they don't exist.
    # Allows for `output_file` to be a relative path.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, mode="w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary."""

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def configure_logging(logger: logging.Logger, console_logging: bool = True) -> None:
    """Configure logging for this program.

    By default, logs are written to a timestamped file in `logs/` and to the console.
    Console logging can be disabled by passing `console_logging=False`.

    :param console_logging: Whether to enable console (stdout) logging.
    """
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{logger.name}_{timestamp}.log"  # use logger name for file

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console_logging:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
