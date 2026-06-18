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
from pymarc import Record


# Module-level logger used throughout this module.
# Handlers are configured explicitly via `configure_logging`.
logger = logging.getLogger(Path(__file__).stem)


def configure_logging(console_logging: bool = True) -> None:
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


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments for the program."""
    parser = argparse.ArgumentParser(
        description="Prepare JSON metadata for MAMS ingestion."
    )
    parser.add_argument(
        "-c",
        "--config_file",
        help="Path to configuration file with API credentials.",
        required=True,
    )
    parser.add_argument(
        "-b",
        "--batch_number",
        type=str,
        required=False,
        help="Alphanumeric batch number to fetch records from Digital Data.",
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


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary."""

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


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


def _get_records_by_batch_number(
    batch_number: str,
    digital_data_client: DigitalDataClient,
) -> list[dict]:
    """Get records filtered by batch number from the Digital Data application.

    :param batch_number: The alphanumeric batch number to filter by.
    :param digital_data_client: The DigitalDataClient instance to use to get the records.
    :return: A list of records.
    """
    all_records: list[dict] = []
    offset = 0
    while True:
        response = digital_data_client.get_records(
            query=batch_number,
            fields=["batch_number"],
            offset=offset,
        )
        records = response.get("records", [])
        all_records.extend(records)
        offset += len(records)
        # Break if pagination reaches end of records,
        # or if a problem causes API to return no records before then.
        if offset >= response.get("total_records", 0) or not records:
            break
    return all_records


def _get_alma_bib_record(
    inv_no_stem: str,
    alma_sru_client: AlmaSRUClient,
) -> Record | None:
    """Get the Alma bib record for the provided inventory number,
    retrying with suffixes "T", "M", and "R" if no record is found without suffix.

    :param inv_no_stem: The base inventory number to search for.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :return: Matching Alma bib record, or None if no record is found.
    """
    # Try no suffix first, then "T", "M", and "R".
    # NOTE: The additional suffixes are a shim
    # to deal with inconsistent inventory numbers across systems.
    suffixes = ["", "T", "M", "R"]
    inv_nos_to_check = [inv_no_stem + suffix for suffix in suffixes]
    # There may not be any matches - if so, this is a "1-to-1" record,
    # so we'll use only DD and FM data.
    bib_record = None
    for inv_no in inv_nos_to_check:
        search_results = alma_sru_client.search_by_call_number(inv_no)
        filtered_bib_records: list[Record] = filter_by_inventory_number_and_library(
            search_results, inv_no
        )
        if filtered_bib_records:
            # Take the first record that matches the inventory number and is from FTVA
            bib_record = filtered_bib_records[0]
            if inv_no != inv_no_stem:
                logger.info(
                    f"Inventory number '{inv_no_stem}' from DD "
                    f"matched to '{inv_no}' in Alma."
                )
            break
    return bib_record


def _set_record_type_and_match_asset(
    digital_data_record: dict, metadata_record: dict
) -> dict:
    """Set the `record_type` property on the metadata record,
    and if applicable, the `match_asset` property for tracks.

    :param digital_data_record: The Digital Data record to process.
    :param metadata_record: The metadata record to update.
    :return: The updated metadata record.
    """
    # Default to `record_type=asset` for all metadata records
    metadata_record["record_type"] = "asset"

    # Now check if the DD record is a track,
    # indicated by an incoming relationship with a type of `isTrackOf`
    incoming_relationships = digital_data_record.get("incoming_relationships", [])
    # Next() returns the first relationship with a type of `isTrackOf`,
    # or None if no such relationship is found.
    track_relationship = next(
        (
            relationship
            for relationship in incoming_relationships
            if relationship.get("relationship_type", "") == "isTrackOf"
        ),
        None,
    )
    # If a track relationship is found, set `record_type=track`
    # and `match_asset` to the source UUID for the relationship.
    if track_relationship:
        metadata_record["record_type"] = "track"
        metadata_record["match_asset"] = track_relationship.get("source_uuid", "")
    return metadata_record


def _compare_inventory_numbers(record_with_match: dict, matched_record: dict) -> dict:
    """Compare the inventory numbers of two records related via `match_asset`.

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


def _validate_match_asset_relationships(metadata_records: list[dict]) -> list[dict]:
    """Validate that records with a `match_asset` property point to a record in the batch,
    and that the inventory numbers of the related records match.

    :param metadata_records: List of metadata records.
    :return: List of metadata records with validated `record_type` values.
    """
    for record in metadata_records:
        # If the record has a `match_asset` value,
        # validate that the value points to a record in the batch,
        # then compare the inventory numbers of the related records
        if record.get("match_asset"):
            # Returns first record with a matching UUID, or None if no match is found
            matched_record = next(
                (r for r in metadata_records if r.get("uuid") == record["match_asset"]),
                None,
            )
            if not matched_record:
                logger.error(
                    f"Match asset {record['match_asset']} "
                    f"for record {record['uuid']} not found in batch."
                )
                continue
            # Compare the inventory numbers of the related records
            # and overwrite the `record_type` value if necessary
            record = _compare_inventory_numbers(record, matched_record)
    return metadata_records


def _process_digital_data_records(
    digital_data_records: list[dict],
    alma_sru_client: AlmaSRUClient,
    filemaker_client: FilemakerClient,
) -> list[dict]:
    """Process Digital Data records by passing them to `ftva-etl`,
    alongside corresponding FileMaker and/or Alma records,
    then extending the resulting base metadata record with additional properties,
    to return a list of JSON metadata records.

    :param digital_data_records: Digital Data records to process.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :param filemaker_client: The FilemakerClient instance to use to get the FM record.
    :return: A list of metadata records for ingest into the MAMS.
    """
    metadata_records = []

    for digital_data_record in digital_data_records:
        # Adding `try/except` block to prevent the program from crashing if a record
        # is not found. This would happen if the dev and prod databases are out of sync.
        try:
            inventory_number = digital_data_record["inventory_number"]

            bib_record = _get_alma_bib_record(inventory_number, alma_sru_client)
            if not bib_record:
                logger.warning(
                    f"No Alma bib record found for inventory number '{inventory_number}' "
                    f"on DD record {digital_data_record['id']}. "
                    "Proceeding with DD and FM data only."
                )
                continue

            filemaker_record = filemaker_client.search_by_inventory_number(
                inventory_number
            )[0]
        except HTTPError as error:
            if error.response.status_code == 404:
                logger.error(
                    f"Record {digital_data_record['id']} not found in Digital Data."
                )
            else:
                logger.error(error)
            continue

        # Run main metadata processing function from `ftva-etl`
        # to get base metadata record
        metadata_record = get_mams_metadata(
            digital_data_record=digital_data_record,
            filemaker_record=filemaker_record,
            bib_record=bib_record,
        )

        # Now extend metadata record with `record_type`,
        # and `match_asset` for tracks, if applicable.
        metadata_record = _set_record_type_and_match_asset(
            digital_data_record, metadata_record
        )

        # Now add `file_type` property for DPX and DCP records
        file_type = digital_data_record.get("file_type", "")
        if file_type in ["DPX", "DCP"]:
            metadata_record["file_type"] = file_type

        metadata_records.append(metadata_record)
    return metadata_records


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
    configure_logging(console_logging=not args.disable_console_logging)
    config = _get_config(args.config_file)

    alma_sru_client, filemaker_client, digital_data_client = _initialize_clients(config)

    logger.info(
        f"Fetching records for batch number {args.batch_number} from Digital Data..."
    )
    digital_data_records = _get_records_by_batch_number(
        args.batch_number, digital_data_client
    )
    logger.info(
        f"Retrieved {len(digital_data_records)} records for batch number {args.batch_number}."
    )

    metadata_records = _process_digital_data_records(
        digital_data_records, alma_sru_client, filemaker_client
    )

    metadata_records = _validate_match_asset_relationships(metadata_records)

    output_dict = {"media": {"assets": metadata_records}}

    output_filename_stem = f"dd_records_ingest_{args.batch_number}"
    date_suffix = datetime.now().strftime("%Y-%m-%d")
    output_path = Path(args.output_dir, f"{output_filename_stem}_{date_suffix}.json")
    _write_output_file(output_path, output_dict)

    logger.info(f"Output JSON file saved to '{output_path}'")

    asset_count, track_count = _count_assets_and_tracks(metadata_records)
    logger.info(
        f"Processing complete. {asset_count} assets and {track_count} tracks processed."
    )


if __name__ == "__main__":
    main()
