import json
import argparse
import tomllib
import logging
import spacy
from datetime import datetime
from pathlib import Path
from ftva_etl import (
    AlmaSRUClient,
    FilemakerClient,
    DigitalDataClient,
    get_mams_metadata,
)
from ftva_etl.metadata.utils import filter_by_inventory_number_and_library

# For type hints
from pymarc import Record as Pymarc_Record
from fmrest.record import Record as FM_Record

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
        required=True,
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
    :param data: Dict or list of dicts to write to the output file."""
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


def _get_alma_bib_record_with_possible_suffix(
    inv_no_stem: str,
    alma_sru_client: AlmaSRUClient,
) -> Pymarc_Record | None:
    """Get the first matching Alma bib record for the provided inventory number,
    retrying with suffixes "T", "M", and "R" if no record is found without suffix.

    :param inv_no_stem: The base inventory number to search for.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :return: The first Alma record matching the inventory number,
        or None if no record is found.
    """
    # Try no suffix first, then "T", "M", and "R".
    # NOTE: The additional suffixes are a shim
    # to deal with inconsistent inventory numbers across systems.
    suffixes = ["", "T", "M", "R"]
    inv_nos_to_check = [inv_no_stem + suffix for suffix in suffixes]
    bib_record = None
    for inv_no in inv_nos_to_check:
        search_results = alma_sru_client.search_by_call_number(inv_no)
        filtered_bib_records: list[Pymarc_Record] = (
            filter_by_inventory_number_and_library(search_results, inv_no)
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


def _get_filemaker_record(
    inventory_number: str,
    filemaker_client: FilemakerClient,
) -> FM_Record | None:
    """Get the first matching FileMaker record for the provided inventory number,
    or None if no record is found.

    :param inventory_number: The inventory number to search for.
    :param filemaker_client: The FilemakerClient instance to use to get the FM record.
    :return: The first FileMaker record matching inventory number,
        or None if no record is found.
    """
    filemaker_records = filemaker_client.search_by_inventory_number(inventory_number)
    # If search returns multiple records, return only the first
    return filemaker_records[0] if filemaker_records else None


def _get_metadata_records(
    digital_data_records: list[dict],
    alma_sru_client: AlmaSRUClient,
    filemaker_client: FilemakerClient,
) -> list[dict]:
    """For each Digital Data record,
    fetch the corresponding FileMaker record, and possibly the Alma record,
    then use `ftva_etl` to get the resulting metadata record.

    :param digital_data_records: Digital Data records to process.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :param filemaker_client: The FilemakerClient instance to use to get the FM record.
    :return: A list of metadata records formatted for ingest into the MAMS.
    """
    metadata_records = []
    # Load spacy model used by `ftva_etl` once per batch,
    # to avoid loading it in the package for each record
    nlp_model = spacy.load("en_core_web_md")

    for digital_data_record in digital_data_records:
        # Use inventory number to find corresponding FM record and possibly Alma record
        inventory_number = digital_data_record["inventory_number"]

        filemaker_record = _get_filemaker_record(inventory_number, filemaker_client)
        # Metadata output requires DD-FM match at minimum,
        # so log an error and skip the current DD record if no FM record is found.
        if not filemaker_record:
            logger.error(
                f"No FileMaker record found for inventory number '{inventory_number}' "
                f"on DD record {digital_data_record['id']}. "
                "Skipping current record."
            )
            continue  # skip to next DD record

        bib_record = _get_alma_bib_record_with_possible_suffix(
            inventory_number, alma_sru_client
        )
        # Missing Alma record is OK, so log a warning and proceed with batch
        if not bib_record:
            logger.warning(
                f"No Alma bib record found for inventory number '{inventory_number}' "
                f"on DD record {digital_data_record['id']}. "
                "Proceeding with DD and FM data only."
            )

        # Get formatted metadata record from `ftva_etl`
        # using DD record, corresponding FM record, and possibly Alma record
        metadata_record = get_mams_metadata(
            digital_data_record=digital_data_record,
            filemaker_record=filemaker_record,
            bib_record=bib_record,  # can be None if no Alma record found for inv no
            nlp_model=nlp_model,
        )

        metadata_records.append(metadata_record)
    return metadata_records


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
            logger.error(
                f"Match asset {match_asset_uuid} for record {record['uuid']} "
                f"not found in batch."
            )
            return False

        # Now check inventory numbers, using the first inv no for each record
        record_inv = (record.get("inventory_numbers") or [None])[0]
        matched_record_inv = (matched_record.get("inventory_numbers") or [None])[0]

        # Fail validation if inventory numbers do not match
        if record_inv != matched_record_inv:
            logger.error(
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

    metadata_records = _get_metadata_records(
        digital_data_records, alma_sru_client, filemaker_client
    )

    # If match_asset relationships are invalid, log an error and exit
    if not _validate_match_asset_relationships(metadata_records):
        logger.error(
            "Invalid match_asset relationships found in metadata records. Review logs for details."
        )
        return

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
