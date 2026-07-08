import argparse
import csv
import logging
import sys

from datetime import datetime
from pathlib import Path
from ftva_etl import AlmaSRUClient, FilemakerClient, get_mams_metadata_ndm
from utils import alma_utils, generate_metadata_utils as gm_utils

from fmrest.record import Record

# Module-level logger used throughout this module.
# Handlers are configured explicitly via `_configure_logging`.
LOGGER = logging.getLogger(Path(__file__).stem)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def _get_fm_inventory_records_indexed_by_inventory_id(
    config: dict,
) -> dict[int, Record]:
    """Get all digital inventory records indexed by inventory ID
    from the "NEW DIGITAL_API" layout in Filemaker.

    :param config: Config dict with Filemaker API credentials.
    :return: A dict of digital inventory records indexed by inventory ID.
    """
    fm_inventory_layout = "NEW DIGITAL_API"
    fm_client = FilemakerClient(
        config["filemaker"]["user"],
        config["filemaker"]["password"],
        layout=fm_inventory_layout,
    )
    # `digital_record` field necessary to filter for digital inventory records
    query = [{"digital_record": "1"}]
    fm_inventory_records = fm_client.find_all_records(query=query)
    return {record["inventory_id"]: record for record in fm_inventory_records}


def _get_fm_item_records_indexed_by_uuid(config: dict) -> dict[str, Record]:
    """Get all item unit records indexed by UUID
    from the "New Digital DMIU" layout in Filemaker.

    :param config: Config dict with Filemaker API credentials.
    :return: A dict of item unit records indexed by UUID.
    """

    # Item unit records are stored in the "Digital Media Item Unit" table,
    # accessed via the "New Digital DMIU" layout
    fm_item_unit_layout = "New Digital DMIU"
    fm_client = FilemakerClient(
        config["filemaker"]["user"],
        config["filemaker"]["password"],
        layout=fm_item_unit_layout,
    )
    # `find_all_records` requires a query parameter, so we use a wildcard on UUID here,
    # which should never be null and therefore yields all records
    fm_item_unit_records = fm_client.find_all_records(query=[{"UUID": "*"}])
    # Index item units by UUID for quick lookup later
    return {record["UUID"]: record for record in fm_item_unit_records}


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
    # Alma SRU client for use below
    alma_sru_client = AlmaSRUClient()

    # Build indexes for Filemaker item records and inventory records for quick lookup below
    fm_item_records_indexed_by_uuid = _get_fm_item_records_indexed_by_uuid(config)
    fm_inventory_records_indexed_by_inventory_id = (
        _get_fm_inventory_records_indexed_by_inventory_id(config)
    )

    metadata_records = []
    for row in input_data:
        # Lookup item record by UUID in index, failing batch if any not found
        item_record = fm_item_records_indexed_by_uuid.get(row["UUID"])
        if not item_record:
            LOGGER.error(f"Item record not found for UUID {row['UUID']}")
            sys.exit(1)
        # Now lookup inventory record using `inventory_id_fk` from item record,
        # failing batch if the related inventory record is not found
        inventory_record = fm_inventory_records_indexed_by_inventory_id.get(
            item_record["inventory_id_fk"]
        )
        if not inventory_record:
            LOGGER.error(
                f"Inventory record not found for inventory ID {item_record['inventory_id_fk']} "
                f"on item record {item_record['UUID']}"
            )
            sys.exit(1)
        # Search for Alma bib record matching inventory number, with retries for possible suffixes
        alma_bib_record = alma_utils.get_alma_bib_record_with_possible_suffix(
            inventory_record["inventory_no"], alma_sru_client, LOGGER
        )
        # Set match asset if present
        match_asset = row["match asset UUID"].strip() or None

        metadata_record = get_mams_metadata_ndm(
            item_record, inventory_record, alma_bib_record, match_asset
        )
        metadata_records.append(metadata_record)
    return metadata_records


# ---------------------------------------------------------------------------
# CLI arguments, logging, and input file loading
# ---------------------------------------------------------------------------
def _read_input_file(input_file: str | Path) -> list[dict]:
    """Read the input file and return the data as a list of dictionaries.

    :param input_file: Path to the input CSV file.
    :return: A list of dictionaries."""
    with open(input_file, "r", encoding="utf-8") as file:
        return [row for row in csv.DictReader(file)]


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
    config = gm_utils.get_config(args.config_file)

    input_data = _read_input_file(args.input_file)

    metadata_records = _get_metadata_records(config, input_data)

    # If match_asset relationships are invalid, log an error and exit
    if not gm_utils.validate_match_asset_relationships(metadata_records):
        LOGGER.error(
            "Invalid match_asset relationships found in metadata records. Review logs for details."
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
