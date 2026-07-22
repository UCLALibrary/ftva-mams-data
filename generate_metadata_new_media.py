import argparse
import logging
import spacy
import sys

from datetime import datetime
from pathlib import Path
from ftva_etl import AlmaSRUClient, FilemakerClient, get_mams_metadata_ndm
from utils import alma_utils, generate_metadata_utils as gm_utils

from fmrest.record import Record

# Module-level logger used throughout this module.
# Handlers are configured explicitly via `gm_utils.configure_logging`.
LOGGER = logging.getLogger(Path(__file__).stem)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def _get_inventory_record_by_inventory_id(
    fm_client: FilemakerClient, inventory_id: int
) -> Record:
    """Get an inventory record by inventory ID from the "NEW DIGITAL_API" layout in Filemaker.

    :param fm_client: An authenticated Filemaker client instance.
    :param inventory_id: Inventory ID of the inventory record to get.
    :return: The inventory record.
    :raises SystemExit: if the inventory record is not found or if multiple records are found.
    """
    fm_inventory_layout = "NEW DIGITAL_API"
    # This query syntax matches the provided inventory ID exactly
    query = [{"inventory_id": f"=={inventory_id}"}]
    # Using `find_all_records` because there is no built-in `fmrest` method
    # for getting a single record by an arbitrary field.
    # TODO: consider adding a `find_one_record` method to the FilemakerClient class.
    # Default layout on `fm_client` is overridden using `request_layout` parameter.
    result = fm_client.find_all_records(query=query, request_layout=fm_inventory_layout)
    if not result:
        LOGGER.error(f"Inventory record not found for inventory ID {inventory_id}")
        sys.exit(1)
    # This should never happen, but just in case, exit with an error
    if len(result) > 1:
        LOGGER.error(
            f"Multiple inventory records found for inventory ID {inventory_id}"
        )
        sys.exit(1)
    return result[0]


def _get_item_record_by_uuid(fm_client: FilemakerClient, uuid: str) -> Record:
    """Get an item record by UUID from the "New Digital DMIU" layout in Filemaker.

    :param fm_client: An authenticated Filemaker client instance.
    :param uuid: UUID of the item record to get.
    :return: The item record.
    :raises SystemExit: if the item record is not found or if multiple records are found.
    """
    fm_item_unit_layout = "New Digital DMIU"
    # This query syntax matches the provided UUID exactly
    query = [{"UUID": f"=={uuid}"}]
    # Using `find_all_records` because there is no built-in `fmrest` method
    # for getting a single record by an arbitrary field.
    # TODO: consider adding a `find_one_record` method to the FilemakerClient class.
    # Default layout on `fm_client` is overridden using `request_layout` parameter.
    result = fm_client.find_all_records(query=query, request_layout=fm_item_unit_layout)
    # If no records are found, or if there are multiple records found, exit with an error
    if not result:
        LOGGER.error(f"Item record not found for UUID {uuid}")
        sys.exit(1)
    # Not sure that unique constraints are enforced on UUIDs,
    # so exit with an error if multiple records are found
    if len(result) > 1:
        LOGGER.error(f"Multiple item records found for UUID {uuid}")
        sys.exit(1)
    return result[0]


# ---------------------------------------------------------------------------
# Metadata generation
# ---------------------------------------------------------------------------
def _get_metadata_records(config: dict, input_data: list[dict]) -> list[dict]:
    """Get metadata records for MAMS ingest,
    using input data to fetch necessary sources from Filemaker and possibly Alma.

    :param config: Config dict with API credentials.
    :param input_data: Input data as a list of dicts.
    :return: A list of metadata records.
    """
    # Load spacy model used by `ftva_etl` once per batch,
    # to avoid loading it in the package for each record
    nlp_model = spacy.load("en_core_web_md")

    # Clients for data sources used below
    fm_client = FilemakerClient(
        config["filemaker"]["user"],
        config["filemaker"]["password"],
    )
    alma_sru_client = AlmaSRUClient()

    metadata_records = []
    for row in input_data:
        # Get item record by provided UUID,
        # then get inventory record using `inventory_id_fk` from item record
        item_record = _get_item_record_by_uuid(fm_client, row["UUID"])
        inventory_record = _get_inventory_record_by_inventory_id(
            fm_client, item_record["inventory_id_fk"]
        )
        # Search for Alma bib record matching inventory number, with retries for possible suffixes
        alma_bib_record = alma_utils.get_alma_bib_record_with_possible_suffix(
            inventory_record["inventory_no"], alma_sru_client, LOGGER
        )
        # Set match asset if present
        match_asset = row["match asset UUID"].strip() or None

        metadata_record = get_mams_metadata_ndm(
            item_record, inventory_record, alma_bib_record, match_asset, nlp_model
        )
        metadata_records.append(metadata_record)
    return metadata_records


# ---------------------------------------------------------------------------
# CLI arguments
# ---------------------------------------------------------------------------
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
    gm_utils.configure_logging(LOGGER, not args.disable_console_logging)
    config = gm_utils.get_config(args.config_file)

    input_data = gm_utils.read_input_file(args.input_file)
    LOGGER.info(f"Loaded {len(input_data)} input records from {args.input_file}")

    metadata_records = _get_metadata_records(config, input_data)

    # If there are any validation problems, log them and exit without writing output file.
    # Inventory numbers are expected to differ for NDM, so we disable inventory number validation.
    validation_problems = gm_utils.validate_match_asset_relationships(
        metadata_records, check_inventory_numbers=False
    )
    if validation_problems:
        for problem in validation_problems:
            LOGGER.error(problem)
        LOGGER.error(
            "Problems found with match_asset relationships. "
            "Please fix the issues and try again."
        )
        return

    output_dict = {"media": {"assets": metadata_records}}

    output_path = Path(
        args.output_dir,
        f"ndm_records_ingest_{datetime.now().strftime("%Y-%m-%d")}.json",
    )
    gm_utils.write_output_file(output_path, output_dict)

    LOGGER.info(f"Output JSON file saved to '{output_path}'")

    asset_count, track_count = gm_utils.count_assets_and_tracks(metadata_records)
    LOGGER.info(
        f"Processing complete. {asset_count} assets and {track_count} tracks processed."
    )


if __name__ == "__main__":
    main()
