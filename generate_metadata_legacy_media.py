import argparse
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
from utils import alma_utils, generate_metadata_utils as gm_utils

# For type hints
from fmrest.record import Record as FM_Record

# Module-level logger used throughout this module.
# Handlers are configured explicitly via `configure_logging`.
LOGGER = logging.getLogger(Path(__file__).stem)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
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
            LOGGER.error(
                f"No FileMaker record found for inventory number '{inventory_number}' "
                f"on DD record {digital_data_record['id']}. "
                "Skipping current record."
            )
            continue  # skip to next DD record

        bib_record = alma_utils.get_alma_bib_record_with_possible_suffix(
            inventory_number, alma_sru_client, LOGGER
        )
        # Missing Alma record is OK, so log a warning and proceed with batch
        if not bib_record:
            LOGGER.warning(
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


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    args = _get_arguments()
    gm_utils.configure_logging(LOGGER, not args.disable_console_logging)
    config = gm_utils.get_config(args.config_file)

    alma_sru_client, filemaker_client, digital_data_client = _initialize_clients(config)

    LOGGER.info(
        f"Fetching records for batch number {args.batch_number} from Digital Data..."
    )
    digital_data_records = _get_records_by_batch_number(
        args.batch_number, digital_data_client
    )
    LOGGER.info(
        f"Retrieved {len(digital_data_records)} records for batch number {args.batch_number}."
    )

    metadata_records = _get_metadata_records(
        digital_data_records, alma_sru_client, filemaker_client
    )

    # If match_asset relationships are invalid, log an error and exit
    if not gm_utils.validate_match_asset_relationships(metadata_records):
        LOGGER.error(
            "Invalid match_asset relationships found in metadata records. Review logs for details."
        )
        return

    output_dict = {"media": {"assets": metadata_records}}

    output_filename_stem = f"dd_records_ingest_{args.batch_number}"
    date_suffix = datetime.now().strftime("%Y-%m-%d")
    output_path = Path(args.output_dir, f"{output_filename_stem}_{date_suffix}.json")
    gm_utils.write_output_file(output_path, output_dict)

    LOGGER.info(f"Output JSON file saved to '{output_path}'")

    asset_count, track_count = gm_utils.count_assets_and_tracks(metadata_records)
    LOGGER.info(
        f"Processing complete. {asset_count} assets and {track_count} tracks processed."
    )


if __name__ == "__main__":
    main()
