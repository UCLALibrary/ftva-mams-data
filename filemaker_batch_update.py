import csv
import tomllib
import logging
import argparse
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from ftva_etl import FilemakerClient
from fmrest.exceptions import FileMakerError
from fmrest.record import Record

import time

# Creating module-level logger here;
# handlers are configured via `_configure_logging`.
logger = logging.getLogger(Path(__file__).stem)

_PAGE_SIZE = 5000


# --------------------
# Helper functions
# --------------------
def _configure_logging(dry_run: bool = False) -> None:
    """Configure logging for this program.

    Creates two handlers for the logger instantiated above,
    one for the plain-text `.log` file and one for the console.

    :param dry_run: Determines whether dry run suffix is added to log and CSV file names.
    """
    # Don't propagate to root logger, to avoid duplicate logs
    logger.propagate = False
    # Set level on logger to low value; handlers can set their own higher levels as needed
    logger.setLevel(logging.DEBUG)

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_DRY_RUN" if dry_run else ""

    log_file = logs_dir / f"{logger.name}_{timestamp}{suffix}.log"

    file_formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    console_formatter = logging.Formatter("%(message)s")  # just messages for console

    # Set up file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)  # lower lvl so change logs written to file

    # Set up console output handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)  # higher lvl so no change logs to console

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def _get_arguments() -> argparse.Namespace:
    """Parse and return command-line arguments.

    :return: Parsed arguments as a Namespace object.
    """
    parser = argparse.ArgumentParser(
        description="Batch update Filemaker records by applying per-field transformation rules.",
    )
    parser.add_argument(
        "-c",
        "--config_file",
        type=str,
        required=True,
        help="Path to TOML configuration file containing Filemaker API credentials.",
    )
    parser.add_argument(
        "-f",
        "--fields",
        type=str,
        nargs="+",
        required=True,
        metavar="FIELD",
        help="One or more FM field names to process.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="DRY RUN: preview changes without writing anything to Filemaker.",
    )
    return parser.parse_args()


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the TOML configuration file.
    :return: Configuration dict.
    """
    with open(config_file_name, "rb") as f:
        return tomllib.load(f)


# --------------------
# Transformers
# --------------------
def _load_mapping(path: Path) -> dict[str, str]:
    """Read a two-column CSV with 'from' and 'to' headers into a substitution dict.

    :param path: Path to the mapping CSV file.
    :return: Dict mapping each 'from' value to its corresponding 'to' value.
    """
    # Load mapping CSV file with UTF-8 encoding
    with open(path, encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return {row["from"]: row["to"] for row in reader}


def _trim_whitespace(value: str) -> str:
    """Strip leading and trailing whitespace from provided value."""
    return value.strip()


def _standardize_delimiters(value: str) -> str:
    """Standardize delimiters in provided value."""
    return value.replace(";", "\r")


def _replace_ampersand(value: str) -> str:
    """Replace ampersand with 'and' in provided value."""
    return value.replace("&", "and")


def _initialize_client(config: dict) -> FilemakerClient:
    """Initialize and return a configured Filemaker client.

    :param config: Program configuration dict loaded from TOML.
    :return: An initialized `FilemakerClient` instance.
    :raises FileMakerError: If the connection to Filemaker fails.
    """
    try:
        client = FilemakerClient(
            user=config["filemaker"]["user"],
            password=config["filemaker"]["password"],
        )
        logger.info("Connected to Filemaker.")
        return client
    except FileMakerError as e:
        logger.error(f"Failed to connect to Filemaker: {e}")
        raise


def _validate_fields(field_names: list[str], fm_record: Record) -> None:
    """Verify that every requested field name exists on the given Filemaker record.

    :param field_names: Target field names to validate.
    :param fm_record: A representative Filemaker record to check field names against.
    :raises ValueError: If one or more field names are not present on the record.
    """
    fm_fields = fm_record.keys()
    bad_fields = [name for name in field_names if name not in fm_fields]
    if bad_fields:
        raise ValueError(
            f"The following field(s) were not found in Filemaker: "
            f"{bad_fields}. "
            f"Available fields are: {sorted(fm_fields)}"
        )


def _get_all_records(fm_client: FilemakerClient) -> Iterator[Record]:
    """Yield every record in the Filemaker database, paginating automatically.

    :param fm_client: A configured FilemakerClient instance.
    :yields: Individual fmrest `Record` objects.
    """
    offset = 1
    while True:
        logger.info(
            f"Getting records from offset {offset} to {offset + _PAGE_SIZE - 1}..."
        )
        try:
            records = fm_client._fms.get_records(
                offset=offset,
                limit=_PAGE_SIZE,
            )
        except FileMakerError as error:
            # FileMakerError doesn't provide the error code as an integer,
            # but rather as a string message, so check the string for
            # error 101, which represents "Record is missing",
            # indicating end of pagination.
            # Filemaker error codes @https://help.claris.com/en/pro-help/content/error-codes.html
            if "error 101" in error.args[0]:
                return  # no more records; pagination complete
            raise
        # After final page reached, keep checking for records until iterator is exhausted
        if not records:
            return

        yield from records
        offset += _PAGE_SIZE


def _apply_transformations(field_name: str, current_value: str) -> str:
    """Apply transformations to the provided field value.

    :param field_name: The field name to transform.
    :param current_value: The current value of the field.
    :return: The transformed value.
    """
    # First apply mappings specified in `filemaker_mappings` directory
    mappings_dir = Path(__file__).parent / "filemaker_mappings"
    mapping_path = mappings_dir / f"{field_name}.csv"
    mapping = _load_mapping(mapping_path)
    current_value = mapping.get(current_value, current_value)

    # Then apply generic transformations
    transforms = [
        _trim_whitespace,
        _standardize_delimiters,
        _replace_ampersand,
    ]
    for transform in transforms:
        current_value = transform(current_value)

    return current_value


def _process_record(
    fm_record: Record,
    field_names: list[str],
    dry_run: bool,
    fm_client: FilemakerClient,
) -> int:
    """Apply transformations to the provided fields on the Filemaker record.

    :param fm_record: The Filemaker record to process and update, if necessary.
    :param field_names: The field names to process.
    :param dry_run: If True, log but do not write changes.
    :param fm_client: Configured `FilemakerClient` instance.
    :return: Number of fields that were changed (or would be).
    """
    record_id: str = str(fm_record.record_id)
    inventory_id: str = str(fm_record.inventory_id)

    # Multiple fields can be changed at once by passing dict to `edit_record`,
    # so collect them all in one dict.
    pending_changes: dict[str, str] = {}

    for field_name in field_names:
        current_value = str(fm_record[field_name])
        new_value = _apply_transformations(field_name, current_value)

        if current_value == new_value:  # skip if no change
            continue

        logger.debug(
            f"UPDATE field_name={field_name!r} "
            f"record_id={record_id!r} inventory_id={inventory_id!r} "
            f"from={current_value!r} to={new_value!r}"
        )

        pending_changes[field_name] = new_value

    if pending_changes and not dry_run:
        # TODO: Create a convenience wrapper around `edit_record` in `ftva_etl` package
        # success = fm_client._fms.edit_record(record_id, pending_changes)
        time.sleep(0.1)
        success = True

        if not success:
            logger.error(
                f"Update failed for record_id={record_id} "
                f"(inventory_id={inventory_id!r}). "
                f"Filemaker last_error={fm_client._fms.last_error}"
            )

    return len(pending_changes)


def _process_batch(
    field_names: list[str],
    fm_client: FilemakerClient,
    dry_run: bool,
) -> dict[str, int]:
    """Apply transformations to the provided fields on the Filemaker records.

    :param field_names: The field names to process.
    :param fm_client: Configured `FilemakerClient` instance.
    :param dry_run: If True, log changes without writing to Filemaker.
    :return: Stats summarizing records processed, updated, and changes applied.
    """
    stats = {
        "records_processed": 0,
        "records_updated": 0,
        "total_changes_applied": 0,
    }
    fields_validated = False

    for fm_record in _get_all_records(fm_client):
        # Validate fields against first record
        if not fields_validated:
            _validate_fields(field_names, fm_record)
            fields_validated = True

        stats["records_processed"] += 1
        change_count = _process_record(fm_record, field_names, dry_run, fm_client)
        if change_count > 0:
            stats["records_updated"] += 1
            stats["total_changes_applied"] += change_count

    return stats


def main() -> None:
    args = _get_arguments()
    _configure_logging(dry_run=args.dry_run)
    config = _get_config(args.config_file)

    if args.dry_run:
        logger.info("DRY RUN: no changes will be written to Filemaker.")

    field_names = args.fields
    logger.info(f"Fields to process: {field_names}")

    fm_client = _initialize_client(config)

    stats = _process_batch(field_names, fm_client, args.dry_run)

    action = "Would update" if args.dry_run else "Updated"
    logger.info(
        f"Processing complete. "
        f"Processed {stats['records_processed']} Filemaker record(s). "
        f"{action} {stats['records_updated']} record(s) "
        f"with {stats['total_changes_applied']} total field change(s)."
    )


if __name__ == "__main__":
    main()
