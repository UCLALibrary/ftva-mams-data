import csv
import json
import argparse
import tomllib
import logging
import sys

from datetime import datetime
from pathlib import Path
from ftva_etl import (
    AlmaSRUClient,
    FilemakerClient,
    get_mams_metadata_for_new_media,
)

# Module-level logger used throughout this module.
# Handlers are configured explicitly via `_configure_logging`.
LOGGER = logging.getLogger(Path(__file__).stem)


# ---------------------------------------------------------------------------
# Main batching logic
# ---------------------------------------------------------------------------
def _get_fm_item_unit_records_for_batch(
    config: dict, input_data: list[dict]
) -> list[dict]:
    """Get the item unit records for the batch from Filemaker.

    :param config: Config dict with Filemaker API credentials.
    :param input_data: Input data as a list of dicts.
    :return: A list of item unit records representing the batch.
    :raises SystemExit: If an input UUID is not found in the item unit records.
    """

    # Item unit records are stored in the "Digital Media Item Unit" table,
    # accessed via the "New Digital DMIU" layout
    fm_item_unit_layout = "New Digital DMIU"
    fm_client = FilemakerClient(
        config["filemaker"]["user"],
        config["filemaker"]["password"],
        layout=fm_item_unit_layout,
    )
    # `find_all_records` returns all records available on the layout
    # by iterating through all pages of results, but it requires a query parameter,
    # so we use a wildcard on UUID, which should never be null and therefore yields all records
    fm_item_unit_records = fm_client.find_all_records(query=[{"UUID": "*"}])
    # Index item units by UUID for quick lookup below
    fm_item_unit_records_by_uuid = {
        record["UUID"]: record for record in fm_item_unit_records
    }
    # Now build the batch by from the input data
    batch_records = []
    for row in input_data:
        batch_record = fm_item_unit_records_by_uuid.get(row["UUID"])
        # Fail the batch if a UUID is not found in the item unit records
        if not batch_record:
            LOGGER.error(
                f"Item unit record not found for UUID: {row['UUID']}. Exiting."
            )
            sys.exit(1)
        batch_records.append(batch_record)
    return batch_records


def _validate_match_asset_relationships(metadata_records: list[dict]) -> bool:
    """For each metadata record with a `match_asset` field, check that:

    1. the match_asset value actually references another record in the batch; and
    2. the first inventory numbers of the two related records are the same.

    :param metadata_records: List of metadata records.
    :return: True if all match_asset relationships are valid, False otherwise.
    """
    # Index records by UUID for quick lookup below
    records_by_uuid = {
        record["uuid"]: record for record in metadata_records if record.get("uuid")
    }

    for record in metadata_records:
        # Skip records without a `match_asset` field
        match_asset_uuid = record.get("match_asset")
        if not match_asset_uuid:
            continue

        matched_record = records_by_uuid.get(match_asset_uuid)
        # Fail validation if the match_asset is not found in the batch
        if not matched_record:
            LOGGER.error(
                f"Match asset {match_asset_uuid} for record {record['uuid']} "
                f"not found in batch."
            )
            return False

        # Now check inventory numbers, using the first inv no for each record
        record_inv = (record.get("inventory_numbers") or [None])[0]
        matched_record_inv = (matched_record.get("inventory_numbers") or [None])[0]

        # Fail validation if inventory numbers do not match
        if record_inv != matched_record_inv:
            LOGGER.error(
                f"Inventory numbers do not match for match_asset relationship "
                f"{record['record_type']} {record['uuid']}: '{record_inv}', "
                f"{matched_record['record_type']} {matched_record['uuid']}: '{matched_record_inv}'"
            )
            return False
    return True


def _count_assets_and_tracks(metadata_records: list[dict]) -> tuple[int, int]:
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


# ---------------------------------------------------------------------------
# File input and output
# ---------------------------------------------------------------------------
def _read_input_file(input_file: str | Path) -> list[dict]:
    """Read the input file and return the data as a list of dictionaries.

    :param input_file: Path to the input CSV file.
    :return: A list of dictionaries."""
    with open(input_file, "r", encoding="utf-8") as file:
        return [row for row in csv.DictReader(file)]


def _write_output_file(output_file: str | Path, data: dict | list[dict]) -> None:
    """Write processed data to a JSON file.

    :param output_file: Path to the output JSON file.
    :param data: Dict or list of dicts to write to the output file."""
    output_path = Path(output_file)
    # Create parent directories if they don't exist.
    # Allows for `output_file` to be a relative path.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, mode="w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


# ---------------------------------------------------------------------------
# CLI arguments, program config, and logging
# ---------------------------------------------------------------------------
def _configure_logging(console_logging: bool = True) -> None:
    """Configure logging for this program.

    By default, logs are written to a timestamped file in `logs/` and to the console.
    Console logging can be disabled by passing `console_logging=False`.

    :param console_logging: Whether to enable console (stdout) logging.
    """
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{LOGGER.name}_{timestamp}.log"  # use logger name for file

    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    if console_logging:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        LOGGER.addHandler(console_handler)


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary."""

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments for the program."""
    parser = argparse.ArgumentParser(
        description="Generate JSON metadata for MAMS ingest from new digital media (NDM) records."
    )
    parser.add_argument(
        "-c",
        "--config_file",
        help="Path to configuration file with API credentials.",
        required=True,
    )
    parser.add_argument(
        "-i",
        "--input_file",
        help="Path to the input CSV file.",
        required=True,
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="output/",
        required=False,
        help="Path to the output directory where JSON files will be saved. Defaults to 'output/'.",
    )
    parser.add_argument(
        "--disable_console_logging",
        action="store_true",
        required=False,
        help="Disable console logging.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Generate JSON metadata for MAMS ingest from new digital media (NDM) records.

    Input:
    - CSV file with UUIDs for item units in Filemaker representing an ingest batch
    - Configuration file with API credentials for Filemaker
    Output:
    - JSON file with metadata for MAMS ingest
    """
    args = _get_arguments()
    _configure_logging(console_logging=not args.disable_console_logging)
    config = _get_config(args.config_file)

    input_data = _read_input_file(args.input_file)

    batch_records = _get_fm_item_unit_records_for_batch(config, input_data)

    metadata_records = _get_metadata_records_for_new_media(batch_records)

    # TODO:
    # 1) Validate match-asset relationships
    # 2) Count assets and tracks
    # 3) Write output
    # 4) Print summary


if __name__ == "__main__":
    main()
