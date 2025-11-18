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
from ftva_etl.metadata.utils import filter_by_inventory_number_and_library
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
    parser.add_argument(
        "--split_dpx_audio",
        action="store_true",
        required=False,
        help="If specified, split output JSON into DPX, DPX Audio, and Non-DPX files.",
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


def _write_output_file(output_file: str | Path, data: dict | list[dict]) -> None:
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
) -> list[dict]:
    """Process input data and return a list of metadata records, plus counts of assets and tracks.

    :param input_data: The input data to process.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :param filemaker_client: The FilemakerClient instance to use to get the FM record.
    :param digital_data_client: The DigitalDataClient instance to use to get the DD record.
    :return: A list of metadata records.
    """
    metadata_records = []

    for row in input_data:
        # Adding `try/except` block to prevent the program from crashing if a record
        # is not found. This would happen if the dev and prod databases are out of sync.
        try:
            digital_data_record = digital_data_client.get_record_by_id(
                row["dl_record_id"]
            )
            inventory_number = digital_data_record["inventory_number"]
            # First get all results from Alma matching the inventory number
            all_bib_records = alma_sru_client.search_by_call_number(inventory_number)
            # Then take the first record that matches the inventory number and is from FTVA library.
            # This prevents false matches from other libraries.
            bib_record = filter_by_inventory_number_and_library(
                all_bib_records, inventory_number
            )[0]
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

        # Add temporary field for file_type to be used later for DPX splitting
        metadata_record["file_type"] = digital_data_record.get("file_type", "")

        metadata_records.append(metadata_record)
    return metadata_records


def _update_match_record_type(record_with_match: dict, matched_record: dict) -> dict:
    """Check if the match_asset relationship is valid between two records. If valid,
    set record_type to 'track' on the record_with_match. If not valid, set record_type
    to 'asset'.

    :param record_with_match: The record that has a match_asset field.
    :param matched_record: The record that is being matched against.
    :return: The updated record_with_match dict with record_type set to 'track' or 'asset'.
    """
    asset_inv_list = matched_record.get("inventory_numbers") or []
    asset_inv = asset_inv_list[0] if len(asset_inv_list) > 0 else None
    track_inv_list = record_with_match.get("inventory_numbers") or []
    track_inv = track_inv_list[0] if len(track_inv_list) > 0 else None

    if asset_inv == track_inv:
        # This is a track
        record_with_match["record_type"] = "track"
        logger.info(
            f"Valid match_asset relationship found for inventory number '{asset_inv}'."
        )
        return record_with_match

    elif not asset_inv or not track_inv:
        # One or both inventory numbers are missing
        # Treat as individual assets
        logger.info(
            f"One or both inventory numbers are missing (asset_inv='{asset_inv}', "
            f"track_inv='{track_inv}'). Treated as individual assets."
        )
        record_with_match["record_type"] = "asset"
        return record_with_match

    else:
        # Inventory numbers do not match
        # Treat as individual assets
        logger.info(
            f"Inventory numbers do not match (asset_inv='{asset_inv}', "
            f"track_inv='{track_inv}'). Treated as individual assets."
        )
        record_with_match["record_type"] = "asset"
        return record_with_match


def _split_dpx_records(metadata_records: list[dict]) -> dict[str, list[dict]]:
    """Split metadata records into DPX, DPX Audio, and Non-DPX categories.

    :param metadata_records: List of metadata records.
    :return: A dictionary with keys 'DPX', 'DPX Audio', and 'Non-DPX', each containing
    a list of corresponding metadata records."""
    dpx_records = []
    dpx_audio_records = []
    non_dpx_records = []

    # Define audio file types for DPX Audio category
    audio_file_types = [
        "WAV",
        "BWF",
        "AIFF",
        "MP3",
        "AVI",
        "RM",
        "RMVB",
        "AMV",
        "ASF",
        "3GPP",
        "3GGP2",
    ]
    # Process each record and categorize
    # We will do two passes: first for DPX assets, then all others.
    # This ensures that when processing DPX Audio records, we have already
    # collected all DPX assets to check for valid match_asset relationships.
    unassigned_records = metadata_records.copy()
    for record in metadata_records:
        inv_list = record.get("inventory_numbers") or []
        inventory_number = inv_list[0] if len(inv_list) > 0 else None
        # Categorize records
        # DPX: file_type = 'DPX', media_type = 'video', asset_type = 'Raw' or 'Intermediate'
        if (
            record.get("file_type", "").upper() == "DPX"
            and record.get("media_type", "").lower() == "video"
            and record.get("asset_type", "").lower() in ["raw", "intermediate"]
        ):
            logging.info(
                f"DPX record found: Inventory Number '{inventory_number}',"
                f" UUID '{record.get('uuid')}'. Adding to DPX JSON."
            )
            record["record_type"] = "asset"
            dpx_records.append(record)
            unassigned_records.remove(record)

    # Second pass for DPX Audio and Non-DPX
    for record in unassigned_records:
        inv_list = record.get("inventory_numbers") or []
        inventory_number = inv_list[0] if len(inv_list) > 0 else None
        # DPX Audio: file_type in list above, media_type = 'audio', asset_type = 'Raw'
        if (
            record.get("file_type", "").upper() in audio_file_types
            and record.get("media_type", "").lower() == "audio"
            and record.get("asset_type", "").lower() == "raw"
        ):
            logging.info(
                f"DPX Audio candidate found: Inventory Number '{inventory_number},"
                f" UUID '{record.get('uuid')}'. Checking match_asset relationship."
            )
            # Check for valid match_asset relationship
            if "match_asset" in record:
                matched_asset_uuid = record["match_asset"]
                matched_asset = next(
                    (r for r in dpx_records if r.get("uuid") == matched_asset_uuid),
                    None,
                )
                if matched_asset:
                    record = _update_match_record_type(record, matched_asset)
                if record.get("record_type") == "track":
                    logging.info(
                        f"Record with Inventory Number '{inventory_number}' "
                        "is a valid DPX Audio track. Adding to DPX Audio JSON."
                    )
                    dpx_audio_records.append(record)
                    continue  # Move to next record if it's a valid track
                elif record.get("record_type") == "asset":
                    # Treated as individual asset
                    non_dpx_records.append(record)
                    continue  # Move to next record if treated as individual asset

        # Non-DPX: all other records
        else:
            logging.info(
                f"Non-DPX record found: Inventory Number '{inventory_number},'"
                f" UUID '{record.get('uuid')}'. Adding to Non-DPX JSON."
            )
            record["record_type"] = "asset"
            non_dpx_records.append(record)
    return {
        "DPX": dpx_records,
        "DPX Audio": dpx_audio_records,
        "Non-DPX": non_dpx_records,
    }


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


def main() -> None:
    args = _get_arguments()
    config = _get_config(args.config_file)

    # Read input file
    logger.info(f"Loading input data from {args.input_file}")
    input_data = _read_input_file(args.input_file)
    logger.info(f"Loaded {len(input_data)} records from input file.")

    alma_sru_client, filemaker_client, digital_data_client = _initialize_clients(config)

    metadata_records = _process_input_data(
        input_data, alma_sru_client, filemaker_client, digital_data_client
    )

    # Save processed data to JSON file named after the input file.
    output_filename_stem = Path(args.input_file).stem
    if args.split_dpx_audio:
        logger.info("Splitting output JSON into DPX, DPX Audio, and Non-DPX files.")
        split_data = _split_dpx_records(metadata_records)
        for key, records in split_data.items():
            # Remove temporary 'file_type' field before output
            for record in records:
                record.pop("file_type", None)
            output_dict = {"media": {"assets": records}}
            filename = f"{output_filename_stem}_{key.replace(' ', '_')}.json"
            _write_output_file(Path(args.output_dir, filename), output_dict)
        logger.info(f"DPX split JSON files saved to '{args.output_dir}'")
    else:
        # Remove temporary 'file_type' field before output
        for record in metadata_records:
            record.pop("file_type", None)
        output_dict = {"media": {"assets": metadata_records}}
        _write_output_file(
            Path(args.output_dir, f"{output_filename_stem}.json"), output_dict
        )
        logger.info(f"Output JSON file saved to '{args.output_dir}'")

    asset_count, track_count = _count_assets_and_tracks(metadata_records)
    logger.info(
        f"Processing complete. {asset_count} assets and {track_count} tracks processed."
    )


if __name__ == "__main__":
    # Make logger available at module level.
    # Otherwise, it's not available when running tests.
    logger = _get_logger()
    main()
