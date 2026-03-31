import tomllib
import logging
import argparse
import re
from string import capwords
from strsimpy.normalized_levenshtein import NormalizedLevenshtein
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from ftva_etl import FilemakerClient
from fmrest.exceptions import FileMakerError
from fmrest.record import Record

# Creating module-level logger here;
# handlers are configured via `_configure_logging`.
logger = logging.getLogger(Path(__file__).stem)


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
    parser.add_argument(
        "--page_size",
        type=int,
        default=5000,
        required=False,
        help="Page size (i.e. `limit` param) for fetching records from Filemaker. Default is 5000.",
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
# Mappings and transformers
#
# TODO: Move this section into a separate module,
# as the number of fields grows.
# --------------------
MAPPINGS = {
    # NOTE: to smooth out casing inconsistencies,
    # all values (except special cases) will be uppercased prior to mapping,
    # so keys need to be provided in uppercase here to ensure consistent mapping.
    # These mappings are intended to standardize variants of the same term into a controlled list,
    # not to handle casing issues, which are treated separately.
    "production_type": {
        "NEWSREEL": "NEWSREELS",
        "TITLES, BKGD, OUTS": "TITLES, BKGD, Overlays",
        "TITLES, BKGD, OVERLAYS": "TITLES, BKGD, Overlays",  # special case: "Overlays" keeps casing
        "TRIMS AND OUTS": "Trims and Outs",  # special case: "Trims and Outs" keeps casing
        "MADE FOR TV MOVIES": "MADE FOR TV MOVIE",  # strip trailing "S"
        "MADE-FOR-TV": "MADE FOR TV MOVIE",
        "SILENT FILMS": "SILENT FILM",
        "FULL SILENT APERTURE 1.33:1": None,  # None means the value will be removed
        "SF": None,
        "SE": None,
    },
    "Language": {  # This key is capitalized to match FM field name
        "FR": "French",
        "ENG": "English",
        "PORTUGUESE FOR BRAZIL": "Portuguese",
        "UNKNOWN": "Undetermined",
        "?": "Undetermined",
        "": "Undetermined",
        "N/A": "No linguistic content",
        "NONE": "No linguistic content",
    },
}

FIELD_DELIMITERS = {
    "production_type": "\r",
    "Language": ", ",
}


def _trim_whitespace(value: str) -> str:
    """Strip leading and trailing whitespace from provided value."""
    return value.strip()


def _replace_ampersand(value: str) -> str:
    """Replace ampersand with 'and' in provided value."""
    special_cases = ["B&W"]  # Cases where we don't want to replace ampersand
    return value.replace("&", "and") if value not in special_cases else value


def _dedupe_repeated_phrase(value: str) -> str:
    """Remove repeated phrases from provided value (e.g. "SHORT SHORT" -> "SHORT")."""
    # LLM generated this regex:
    # it gets the shortest phrase before the first space into a named group "phrase"
    # then looks for the same phrase again after the space, one or more times.
    # The unique phrase can be accessed in the match group "phrase".
    pattern = re.compile(
        r"^(?P<phrase>.+?)\s+(?P=phrase)$", re.IGNORECASE | re.MULTILINE
    )
    match = pattern.match(value)
    return match.group("phrase") if match else value


def _make_uppercase(value: str) -> str:
    """Convert the provided value to uppercase, except for some special cases."""
    special_cases = ["TITLES, BKGD, Overlays", "Trims and Outs"]
    return value.upper() if value not in special_cases else value


def _make_capitalized(value: str) -> str:
    """Convert the provided value to capitalized case."""
    return capwords(value)


def _remove_intertitles(value: str) -> str:
    """Remove "Intertitles" from the provided value, if present."""
    return value.replace("Intertitles", "").strip()


def _normalize_language_spelling(value: str) -> str:
    """Attempt to normalize language spellings, e.g. "Gernan" -> "German"."""
    valid_languages = [
        "Amharic",
        "Arabic",
        "Chinese",
        "Czech",
        "Danish",
        "Dutch",
        "English",
        "Ethiopic",
        "French",
        "German",
        "Hebrew",
        "Hindi",
        "Hungarian",
        "Indonesian",
        "Italian",
        "Japanese",
        "Korean",
        "Navajo",
        "No linguistic content",
        "Norwegian",
        "Persian",
        "Polish",
        "Portuguese",
        "Russian",
        "Spanish",
        "Swedish",
        "Thai",
        "Ukrainian",
        "Undetermined",
        "Vietnamese",
        "Yupik languages",
    ]
    # Use normalized Levenshtein distance to find the closest valid language
    levenshtein = NormalizedLevenshtein()
    closest_language = None
    closest_distance = float("inf")
    for language in valid_languages:
        distance = levenshtein.distance(value, language)
        if distance < closest_distance:
            closest_distance = distance
            closest_language = language
    # If the closest match is close enough, return it; else return original value
    if closest_language is not None and closest_distance < 0.2:
        if closest_language != value:
            # Log the normalization decision, but only if a change is actually being made
            logger.debug(
                f"Normalized language spelling: {value!r} -> {closest_language!r} "
                f"(distance={closest_distance:.2f})"
            )
        return closest_language
    else:
        if value is not None and value.strip() != "":
            logger.debug(f"No close match found for language: {value!r}. ")
        return value


# These list out the transformers to apply for each target field.
# We can reuse generic transformers, but apply them in different orders if need be.
TRANSFORMERS = {
    "production_type": [
        _trim_whitespace,
        _replace_ampersand,
        _dedupe_repeated_phrase,
        _make_uppercase,
        lambda value: MAPPINGS["production_type"].get(
            value, value
        ),  # Apply the mapping defined above
    ],
    "Language": [
        _trim_whitespace,
        _make_capitalized,
        _normalize_language_spelling,
        _dedupe_repeated_phrase,
        _remove_intertitles,
        lambda value: MAPPINGS["Language"].get(value.upper(), value),
    ],
}


def _split_multivalue_field(value: str, delimiter: str) -> list[str]:
    """Split a multi-value field into a list of values, based on the provided delimiter.
    Also trims whitespace from each value and filters out any empty values."""
    if delimiter == ", ":
        # Normalize all possible delimiters to comma for language
        value = re.sub(r"\s*(?:[,;/|]|\band\b|&|\r)\s*", ", ", value)
        logger.debug(f"Normalized delimiters to comma: {value!r}")
    else:
        value = value.replace(";", delimiter)
    return [v.strip() for v in value.split(delimiter)]


def _rejoin_multivalue_field(values: list[str], delimiter: str) -> str:
    """Rejoin list of values into a multivalue field, filtering out any Falsy values
    to avoid whitespace gaps in the final result."""
    # Remove duplicates and empty values
    seen = set()
    filtered = []
    for v in values:

        if v and v not in seen:
            filtered.append(v)
            seen.add(v)
    return delimiter.join(filtered)


def _apply_transformers(field_name: str, raw_value: str) -> str:
    """Apply transformers on the provided field,
    first splitting multi-value fields into a list of values,
    applying the transformers to each value individually,
    then re-joining the results into a single string with the appropriate delimiter.

    :param field_name: The field name to transform.
    :param raw_value: The raw value to transform, possibly a multi-value field.
    :return: The transformed value.
    """
    delimiter = FIELD_DELIMITERS.get(field_name, "\r")  # default to \r if not specified
    split_values = _split_multivalue_field(raw_value, delimiter)
    transformed_values = []
    for value in split_values:
        for transformer in TRANSFORMERS[field_name]:
            value = transformer(value)
        transformed_values.append(value)
    return _rejoin_multivalue_field(transformed_values, delimiter)


# --------------------
# Batch processing functions
# --------------------
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


def _get_all_records(fm_client: FilemakerClient, page_size: int) -> Iterator[Record]:
    """Yield every record in the Filemaker database, paginating automatically.

    :param fm_client: A configured FilemakerClient instance.
    :yields: Individual fmrest `Record` objects.
    """
    logger.info(f"Retrieving records in pages of {page_size}...")
    offset = 1
    while True:
        records = fm_client.get_records(
            offset=offset,
            limit=page_size,
        )
        logger.info(f"Retrieved records {offset} to {offset + len(records) - 1}...")

        # After final page reached, keep checking for records until iterator is exhausted
        if not records:
            return

        yield from records
        offset += page_size


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
    record_id = fm_record.record_id
    inventory_id: str = str(fm_record.inventory_id)

    # Multiple fields can be changed at once by passing dict to `edit_record`,
    # so collect them all in one dict.
    pending_changes: dict[str, str] = {}

    for field_name in field_names:
        current_value = str(fm_record[field_name])
        new_value = _apply_transformers(field_name, current_value)

        if current_value == new_value:  # skip if no change
            continue

        logger.debug(
            f"UPDATE field_name={field_name} "
            f"record_id={record_id} inventory_id={inventory_id} "
            f"from={current_value!r} to={(new_value or '')!r}"  # use `!r` so `\r` is visible in log
        )  # log changes as debug so they don't clutter the console

        pending_changes[field_name] = new_value

    if pending_changes and not dry_run:
        success = fm_client.edit_record(record_id=record_id, field_data=pending_changes)

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
    page_size: int,
) -> dict[str, int]:
    """Apply transformations to the provided fields on the Filemaker records.

    :param field_names: The field names to process.
    :param fm_client: Configured `FilemakerClient` instance.
    :param dry_run: If True, log changes without writing to Filemaker.
    :param page_size: Page size (i.e. `limit` param) for fetching records from Filemaker.
    :return: Stats summarizing records processed, updated, and changes applied.
    """
    stats = {
        "records_processed": 0,
        "records_updated": 0,
        "total_changes_applied": 0,
    }
    fields_validated = False

    for fm_record in _get_all_records(fm_client, page_size):
        # Validate fields against first record.
        # Invalid fields will raise an exception and cause the program to exit,
        # with a message explaining which fields are missing and which are available.
        if not fields_validated:
            _validate_fields(field_names, fm_record)
            fields_validated = True

        change_count = _process_record(fm_record, field_names, dry_run, fm_client)
        stats["records_processed"] += 1
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

    field_names: list[str] = args.fields
    logger.info(f"Fields to process: {field_names}")

    # Log an error and exit if no transformers are defined for any of the provided fields
    fields_with_transformers = [f for f in field_names if f in TRANSFORMERS]
    if not fields_with_transformers:
        logger.error("No transformers defined for any of the provided fields. Exiting.")
        return

    # Log a warning if some of the provided fields don't have transformers defined
    fields_without_transformers = [f for f in field_names if f not in TRANSFORMERS]
    if fields_without_transformers:
        logger.warning(
            f"No transformers defined for field(s): {fields_without_transformers}. "
            "These fields will not be processed."
        )

    fm_client = _initialize_client(config)

    stats = _process_batch(
        fields_with_transformers, fm_client, args.dry_run, args.page_size
    )

    action = "Would update" if args.dry_run else "Updated"
    logger.info(
        f"Processing complete. "
        f"Processed {stats['records_processed']} Filemaker record(s). "
        f"{action} {stats['records_updated']} record(s) "
        f"with {stats['total_changes_applied']} total field change(s)."
    )


if __name__ == "__main__":
    main()
