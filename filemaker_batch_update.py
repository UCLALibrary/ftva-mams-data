import tomllib
import logging
import argparse
import re
from enum import StrEnum
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

# These are delimiter variations used in Filemaker multi-value fields
FM_DELIMITER_PATTERN = r"\s*([,;/|]|\band\b|&|\r)\s*"


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
    "director": {
        "NO DIRECTOR LISTED": "N/A",
        "N/A": "N/A",
        "NULL": "Unknown",
        "UNKNOWN": "Unknown",
        "": "Unknown",
    },
}


class FieldDelimiters(StrEnum):
    production_type = "\r"
    Language = ", "
    director = ", "


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


def _is_initials_chunk(chunk: str) -> bool:
    """True if the chunk is only single-letter initials separated by dots (e.g. A.B. or c.d.e.).

    :param chunk: The chunk to check.
    :return: True if the chunk is only single-letter initials separated by dots, False otherwise.
    """
    # Must be a non-empty string and only contain letters or dots
    if not chunk or not all(c.isalpha() or c == "." for c in chunk):
        return False
    # Split on dots and check that each segment is a single letter
    segments = [s for s in chunk.split(".") if s]
    # Must be at least one segment and each segment must be a single letter
    return bool(segments) and all(len(s) == 1 and s.isalpha() for s in segments)


def _format_initials(chunk: str) -> str:
    """Format an initials chunk to all-uppercase, e.g. a.b.c. -> A.B.C.

    :param chunk: The chunk to format.
    :return: The formatted initials chunk.
    """
    letters = [c for c in chunk if c.isalpha()]
    return ".".join(c.upper() for c in letters) + "."  # add trailing dot


def _standardize_director_name(name: str) -> str:
    """Return a standardized form for director names, based on specs.

    :param name: Raw input name string.
    :return: Standardized output name string.
    """
    # Apply capwords to fully uppercased or fully lowercased names,
    # handling proper casing of hyphenated chunks.
    if name.isupper() or name.islower():
        for chunk in name.split("-"):
            name = name.replace(chunk, capwords(chunk))

    # Address capitalization issue with nicknames,
    # e.g. prevent output of "Rosco 'fatty' Arbuckle",
    # due to `capwords` interpreting quote as first letter in nickname.
    # NOTE: Output nicknames all wrapped in double-quotes.
    name = re.sub(r"[\'\"](.*)[\'\"]", lambda m: f'"{capwords(m.group(1))}"', name)

    # Roman numeral regex adapted from @https://stackoverflow.com/a/267405.
    # It looks for numerals I through IX in a case-insensitive manner,
    # (but not just X, to avoid matching e.g. "Malcolm X"),
    # asserting the numerals have a word boundary before them,
    # and are at the end of the string.
    name = re.sub(
        r"\b(?=[XVI])(IX|IV|V?I{0,3})$",
        lambda m: m.group(0).upper(),
        name,
        flags=re.IGNORECASE,
    )

    # Special token (i.e. substring) "c/o" should be kept as-is, case-insensitive.
    # Regex looks for "c/o" with word boundaries on either side in a case-insensitive manner.
    name = re.sub(r"\bc/o\b", "c/o", name, flags=re.IGNORECASE)

    # Handle issue with capitalizing numbered names, e.g. `1.brad Bird` -> `1. Brad Bird`.
    # Regex looks for 1 or more digits followed by a dot,
    # followed by 0 or more spaces, followed by any characters.
    # The first group is the digits and dot, the second group is the rest of the string.
    # We want to make sure the second group is capitalized correctly,
    # and normalize the space between the groups.
    name = re.sub(
        r"(\d+\.)\s*(.+)",
        lambda m: f"{m.group(1)} {capwords(m.group(2))}",
        name,
    )

    # Handle capitalization of initials after other transformations are applied.
    formatted_chunks = []
    for chunk in name.split():
        if _is_initials_chunk(chunk):
            formatted_chunks.append(_format_initials(chunk))
            continue
        formatted_chunks.append(chunk)
    name = " ".join(formatted_chunks)
    return name


def _parse_credited_names(value: str) -> str:
    """Parse credited names from the provided value, according to specs:

    - Use name following "as", e.g. Lew Landers (as Louis Friedlander) -> Louis Friedlander
    - Use name before "i.e.", e.g. William Goodrich [i.e. Roscoe Arbuckle] -> William Goodrich
    - Use name before "aka", e.g. Marcus aka Sid Marcus -> Marcus
    - Note that "i.e." is normalized in `_split_multivalue_field` to avoid splitting on the comma

    :param value: Raw value string.
    :return: Parsed credited names string.
    """
    # Use name following "as", accounting for possible parens or brackets
    match_as = re.search(
        r"(?:\(|\[)?"  # non-capturing group for possible opening paren or bracket
        r"\bas\b\s*([^\)\]]+)"  # capture name after "as" (excluding closing paren or bracket)
        r"(?:\)|\])?",  # non-capturing group for possible closing paren or bracket
        value,
        re.IGNORECASE,
    )
    if match_as:
        name = match_as.group(1).strip()
        if name:
            return name

    # Use name before "i.e." or "aka", accounting for possible parens or brackets
    match_ie_aka = re.search(
        r"(.*?)\s+"  # capture group for name, follwed by 1 or more spaces
        r"(?:\(|\[)?"  # non-capturing group for possible opening paren or bracket
        r"(?:i\.e\.|aka)",  # non-capturing group for "i.e." or "aka"
        value,
        re.IGNORECASE,
    )
    if match_ie_aka:
        name = match_ie_aka.group(1).strip()
        if name:
            return name

    return value


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
    # First, make sure we have a non-empty string to compare against valid languages
    # If not, return empty string which will eventually be mapped to "Undetermined"
    if not value or value.strip() == "":
        return ""
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
        _dedupe_repeated_phrase,
        _remove_intertitles,
        _normalize_language_spelling,
        lambda value: MAPPINGS["Language"].get(value.upper(), value),
    ],
    "director": [
        _trim_whitespace,
        _parse_credited_names,
        _standardize_director_name,
        lambda value: MAPPINGS["director"].get(value.upper(), value),
    ],
}


def _normalize_multivalue_delimiters(value: str, delimiter: str) -> str:
    """Normalize the delimiters in the provided value to the provided delimiter."""
    # Case-insensitive to catch both " and " and " AND " delimiters
    new_value = re.sub(FM_DELIMITER_PATTERN, delimiter, value, flags=re.IGNORECASE)
    if new_value != value:
        logger.debug(f"Normalized delimiters: {value!r} -> {new_value!r}")
    return new_value


def _split_multivalue_field(
    field_name: str, value: str, delimiter: str
) -> tuple[list[str], bool]:
    """Splits a multi-value field into a list of values, based on the provided delimiter.
    Also trims whitespace from each value and filters out any empty values.

    Also returns a boolean indicating whether to skip transformers,
    to preserve values as-is for certain fields.

    :param field_name: The field name, for special handling of certain fields.
    :param value: The input value to split.
    :param delimiter: The delimiter to split on.
    :return: A list of individual values, and a boolean indicating whether to skip transformers.
    """
    # Strip leading and trailing whitespace,
    # then also strip any leadin or trailing
    # delimiter characters defined for the field.
    # This prevents bad delimiters from being included in output values.
    value = value.strip().strip(delimiter)
    if not value:
        return [""], False

    # Handle special cases
    if field_name == "Language":
        if "N/A" in value:
            logger.debug(
                "Found known value 'N/A' in language field; replacing with 'NONE'."
            )
            value = value.replace("N/A", "NONE")
        # Normalize FM delimiters to comma for language
        value = _normalize_multivalue_delimiters(value, delimiter)
    elif field_name == "director":
        # If value contains "n/a" or "c/o" (case-insensitive),
        # return value as-is, but do not skip transformers.
        if re.search(r"(n/a|c/o)", value, flags=re.IGNORECASE):
            return [value], False

        # Normalize "i.e.," to "i.e." before delimiter normalization
        # so that commas in "i.e.," are not counted as delimiters
        value = re.sub(r"i\.\s*e\.\s*,", "i.e.", value, flags=re.IGNORECASE)

        # Handle cases where right parenthesis `)` is followed by an uppercase letter,
        # inserting a comma and space between them.
        value = re.sub(r"\)[A-Z]", lambda m: f"{m[0][:1]}, {m[0][1:]}", value)

        # If multiple delimiter types are found,
        # return value as-is and skip transformers.
        matches = re.findall(FM_DELIMITER_PATTERN, value)
        if len(set(matches)) > 1:
            return [value], True
        value = _normalize_multivalue_delimiters(value, delimiter)
    # Default to normalizing semicolons with delimiter
    else:
        value = value.replace(";", delimiter)
    # Use list(filter(None, ...)) to filter out any empty values from the split list.
    return [v.strip() for v in list(filter(None, value.split(delimiter)))], False


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
    delimiter = FieldDelimiters[field_name].value
    split_values, skip_transforms = _split_multivalue_field(
        field_name, raw_value, delimiter
    )
    # Values in some fields require no transforms, aside from trimming whitespace,
    # which is handled by the `_split_multivalue_field` function.
    # If `skip_transforms` is True, there should be only one trimmed value in the list.
    if skip_transforms:
        return split_values[0] if split_values else ""
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
            timeout=240,
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

        # Empty records list indicates end of pagination.
        if not records:
            logger.info("Pagination complete. All records retrieved.")
            return

        logger.info(f"Retrieved records {offset} to {offset + len(records) - 1}...")
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
        try:
            success = fm_client.edit_record(
                record_id=record_id, field_data=pending_changes
            )
        except FileMakerError as e:
            # Log the error and continue processing other records
            logger.error(
                f"Skipping record_id={record_id} inventory_id={inventory_id!r} "
                f"due to Filemaker error: {e}. "
                f"Pending changes were: {pending_changes}"
            )
            # Return 0 here to show that no changes were made
            return 0

        # fm_client.edit_record will return False if the update fails without raising an exception,
        # so log that as well and return 0 to show that no changes were made
        if not success:
            logger.error(
                f"Update failed for record_id={record_id} "
                f"(inventory_id={inventory_id!r}). "
                f"Filemaker last_error={fm_client._fms.last_error}"
            )
            return 0

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
        "updates_failed": 0,
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
        elif change_count == 0 and not dry_run:
            stats["updates_failed"] += 1

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
    if stats["updates_failed"] > 0:
        logger.warning(f"{stats['updates_failed']} record update(s) failed.")


if __name__ == "__main__":
    main()
