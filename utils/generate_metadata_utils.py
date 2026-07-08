import json
import logging
import tomllib

from pathlib import Path


def validate_match_asset_relationships(
    metadata_records: list[dict], logger: logging.Logger | None = None
) -> bool:
    """For each metadata record with a `match_asset` field, check that:

    1. the match_asset value actually references another record in the batch; and
    2. the first inventory numbers of the two related records are the same.

    :param metadata_records: List of metadata records.
    :return: True if all match_asset relationships are valid, False otherwise.
    """
    _logger = logger or logging.getLogger(__name__)
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
            _logger.error(
                f"Match asset {match_asset_uuid} for record {record['uuid']} "
                f"not found in batch."
            )
            return False

        # Now check inventory numbers, using the first inv no for each record
        record_inv = (record.get("inventory_numbers") or [None])[0]
        matched_record_inv = (matched_record.get("inventory_numbers") or [None])[0]

        # Fail validation if inventory numbers do not match
        if record_inv != matched_record_inv:
            _logger.error(
                f"Inventory numbers do not match for match_asset relationship "
                f"{record['record_type']} {record['uuid']}: '{record_inv}', "
                f"{matched_record['record_type']} {matched_record['uuid']}: '{matched_record_inv}'"
            )
            return False
    return True


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
