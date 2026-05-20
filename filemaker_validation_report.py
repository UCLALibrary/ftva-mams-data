import argparse
import csv
import logging
import re
import sys
from collections.abc import (
    Callable,
)  # For type hinting single-field validator callables
from datetime import datetime
from pathlib import Path

from fmrest.record import Record

import filemaker_utils as fm_utils

# ---------------------------------------------------------------------------
# Module-level logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(Path(__file__).stem)

# Output columns, matching the spec's required fields plus record_id for
# debugging convenience.
REPORT_FIELDNAMES = [
    "record_id",
    "inventory_id",
    "inventory_no",
    "user_last_modified",
    "date_modified",
    "field",
    "violation",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_null(value: str) -> bool:
    """Return True if *value* is empty or whitespace-only."""
    return not value or not value.strip()


def _field(record: Record, name: str) -> str:
    """Return a field value from *record* as a stripped string, or '' if absent."""
    try:
        return str(record[name] or "").strip()
    except (KeyError, AttributeError):
        return ""


def _make_violation(record: Record, field: str, message: str) -> dict:
    """Build a violation dict in the spec's output format."""
    return {
        "record_id": record.record_id,
        "inventory_id": _field(record, "inventory_id"),
        "inventory_no": _field(record, "inventory_no"),
        "user_last_modified": _field(record, "user_last_modified"),
        "date_modified": _field(record, "date_modified"),
        "field": field,
        "violation": message,
    }


# ---------------------------------------------------------------------------
# Single-field validators
# Each callable takes a string value and returns a list of error messages.
# ---------------------------------------------------------------------------


def _check_null(value: str) -> list[str]:
    """Field must not be null / empty."""
    if _is_null(value):
        return ["Field is null or empty."]
    return []


# ---------------------------------------------------------------------------
# Field -> validator mapping
# ---------------------------------------------------------------------------
# Organised by layout, matching the spec table.  Each entry maps a FM field
# name to an ordered list of single-field validator callables.
#
# Layout abbreviations used in comments:
#   GE  = Analog GE Form
#   DC  = NDM Digital Carrier Layout
#   DS  = NDM Digital Storage Format Layout

FIELD_VALIDATORS: dict[str, list[Callable[[str], list[str]]]] = {
    # ---- Fields present on GE and DC layouts ----
    "production_type": [
        _check_null
    ],  # GE, DC  (cross-field rule also applies; see below)
    "Language": [_check_null],  # GE, DC
    "donor_code": [_check_null],  # GE, DC
    "Acquisition type": [_check_null],  # GE, DC
    "type": [_check_null],  # GE, DC
    "item_unit_holdings": [_check_null],  # GE, DC
    "title": [_check_null],  # GE, DC
    "date_received": [_check_null],  # GE, DC
    "director": [_check_null],  # GE, DC
    "release_broadcast_year": [
        _check_null
    ],  # GE, DC  (cross-field rule also applies; see below)
    # ---- Fields present on DC layout only ----
    # TODO: Enable once NDM Digital Carrier layout is available via API.
    # "Item_unit_number":   [_check_null],  # DC only
    # "file_size":          [_check_null],  # DC only
    # "Creation_date":      [_check_null],  # DC only
    # "audio_class":        [_check_null],  # DC only
    # "retention_status":   [_check_null],  # DC only  (cross-field rule also applies; see below)
    # "asset_type":         [_check_null],  # DC only
    # "sound_format":       [_check_null],  # DC only  (conditional; see _check_cross_field_rules)
    # ---- Fields present on DS layout only ----
    # TODO: Enable once NDM Digital Storage Format layout is available via API.
    # "file_path":          [_check_null],  # DC and DS
    # "Barcode":            [_check_null],  # DS only
    # "Location":           [_check_null],  # DS only
    # ---- Fields present on GE layout only ----
    "format": [_check_null],  # GE only
    "inventory_no": [_check_null],  # GE only
}


# ---------------------------------------------------------------------------
# Cross-field / conditional rules
# ---------------------------------------------------------------------------


def _check_cross_field_rules(record: Record) -> list[dict]:
    """Check rules that depend on the value of more than one field.

    Implements the following rules from the spec:

    1. Where production_type = "TELEVISION SERIES", flag if episode_no or
       episode_title are null.
    2. Where release_broadcast_year = "N/A" or "Unknown", flag if record_date
       is null.
    3. (TODO - DC layout) Where retention_status = "Temporary", flag if
       retention_start_date or retention_end_date are null.
    4. (TODO - DC layout) Where object_purpose = "Preservation (Full)" or
       "Access (Core)", flag if sound_format is null.

    :param record: A fmrest Record object.
    :return: List of violation dicts.
    """
    violations = []

    # Rule 1: TELEVISION SERIES requires episode fields
    production_type = _field(record, "production_type")
    if production_type.upper() == "TELEVISION SERIES":
        if _is_null(_field(record, "episode no.")):
            violations.append(
                _make_violation(
                    record,
                    "episode no.",
                    "episode no. is null but production_type is 'TELEVISION SERIES'.",
                )
            )
        if _is_null(_field(record, "episode_title")):
            violations.append(
                _make_violation(
                    record,
                    "episode_title",
                    "episode_title is null but production_type is 'TELEVISION SERIES'.",
                )
            )

    # Rule 2: N/A or Unknown release_broadcast_year requires record_date
    release_year = _field(record, "release_broadcast_year")
    if release_year.upper() in ("N/A", "UNKNOWN"):
        if _is_null(_field(record, "record_date")):
            violations.append(
                _make_violation(
                    record,
                    "record_date",
                    f"record_date is null but release_broadcast_year is {release_year!r}.",
                )
            )

    # Rule 3: (TODO - DC layout) Temporary retention requires date range
    # retention_status = _field(record, "retention_status")
    # if retention_status.upper() == "TEMPORARY":
    #     if _is_null(_field(record, "retention_start_date")):
    #         violations.append(_make_violation(
    #             record, "retention_start_date",
    #             "retention_start_date is null but retention_status is 'Temporary'."
    #         ))
    #     if _is_null(_field(record, "retention_end_date")):
    #         violations.append(_make_violation(
    #             record, "retention_end_date",
    #             "retention_end_date is null but retention_status is 'Temporary'."
    #         ))

    # Rule 4: (TODO - DC layout) Preservation/access records require sound_format
    # OBJECT_PURPOSES_REQUIRING_SOUND_FORMAT = {
    #     "PRESERVATION (FULL)", "ACCESS (CORE)"
    # }
    # object_purpose = _field(record, "object_purpose")
    # if object_purpose.upper() in OBJECT_PURPOSES_REQUIRING_SOUND_FORMAT:
    #     if _is_null(_field(record, "sound_format(1)")):
    #         violations.append(_make_violation(
    #             record, "sound_format(1)",
    #             f"sound_format is null but object_purpose is {object_purpose!r}."
    #         ))

    return violations


# ---------------------------------------------------------------------------
# Notes field check (stretch goal per spec)
# ---------------------------------------------------------------------------

# Valid section headers as defined in the spec.
_NOTES_HEADERS = {
    "General Notes",
    "Language Notes",
    "Credits",
    "Credits Notes",
    "Dates Notes",
    "Titles Notes",
}

# Pattern for a correctly formatted notes section:
# "Header: <non-empty text><carriage return>"
# We check each header found in the field value.
_NOTES_HEADER_PATTERN = re.compile(
    r"^(?P<header>.+?):\s+(?P<body>.+?)(?:\r|$)",
    re.MULTILINE,
)


def _check_notes_field(record: Record) -> list[dict]:
    """Check the notes field for correct section header formatting.

    The spec requires that any of the recognised headers (e.g. "Language
    Notes", "Credits Notes") must be followed by a colon, a space, body text,
    and a carriage return.  Violations are reported if:
      - A recognised header is present but not followed by ": <text><CR>".
      - A header-like token (word(s) followed by colon) is present that is
        not in the recognised header list, which may indicate a typo.

    This check is marked as a stretch goal in the spec; disable it by removing
    "notes" from FIELD_VALIDATORS if the false-positive rate is too high.

    :param record: A fmrest Record object.
    :return: List of violation dicts (may be empty).
    """
    value = _field(record, "notes")
    if _is_null(value):
        return []

    violations = []

    for header in _NOTES_HEADERS:
        # Check if this header appears in the field at all
        if header not in value:
            continue

        # It's present: verify it's formatted as "Header: <text><CR>"
        pattern = re.compile(
            rf"^{re.escape(header)}:\s+\S.*?(?:\r|$)",
            re.MULTILINE,
        )
        if not pattern.search(value):
            violations.append(
                _make_violation(
                    record,
                    "notes",
                    f"Header {header!r} is present but not correctly formatted. "
                    f"Expected: '{header}: <text><CR>'.",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Per-record validation entry point
# ---------------------------------------------------------------------------


def validate_record(record: Record) -> list[dict]:
    """Run all validation checks against *record* and return violations.

    Runs:
      1. Single-field null checks from FIELD_VALIDATORS.
      2. Cross-field conditional rules from _check_cross_field_rules().
      3. Notes field formatting check from _check_notes_field().

    :param record: A fmrest Record object.
    :return: List of violation dicts with keys matching REPORT_FIELDNAMES.
    """
    record_dict = record.to_dict()
    violations = []

    # 1. Single-field checks
    for field_name, validators in FIELD_VALIDATORS.items():
        if field_name not in record_dict:
            logger.debug(
                f"Field {field_name!r} not on record {record.record_id}; skipping."
            )
            continue
        value = str(record[field_name] or "")
        for validator in validators:
            for message in validator(value):
                v = _make_violation(record, field_name, message)
                violations.append(v)
                logger.debug(
                    f"VIOLATION record_id={record.record_id} "
                    f"inventory_id={v['inventory_id']!r} "
                    f"field={field_name!r}: {message}"
                )

    # 2. Cross-field rules
    for v in _check_cross_field_rules(record):
        violations.append(v)
        logger.debug(
            f"VIOLATION (cross-field) record_id={record.record_id} "
            f"inventory_id={v['inventory_id']!r} "
            f"field={v['field']!r}: {v['violation']}"
        )

    # 3. Notes field
    for v in _check_notes_field(record):
        violations.append(v)
        logger.debug(
            f"VIOLATION (notes) record_id={record.record_id} "
            f"inventory_id={v['inventory_id']!r}: {v['violation']}"
        )

    return violations


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


def _write_csv_report(violations: list[dict], output_path: Path) -> None:
    """Write *violations* to a CSV file at *output_path*.

    :param violations: List of violation dicts from validate_record().
    :param output_path: Destination path; parent directories are created if needed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(violations)
    logger.info(f"Report written to {output_path} ({len(violations)} violation(s)).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report violations of FileMaker validation rules "
            "(Analog and Digital) for FTVA MAMS records."
        )
    )
    parser.add_argument(
        "-c",
        "--config_file",
        type=str,
        required=True,
        help="Path to TOML configuration file containing Filemaker API credentials.",
    )
    parser.add_argument(
        "--page_size",
        type=int,
        default=5000,
        required=False,
        help=(
            "Number of records to fetch per request to Filemaker. " "Default is 5000."
        ),
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=1,
        required=False,
        help=(
            "Offset (position in list of records, NOT `record_id`) to start "
            "fetching records from Filemaker. Only applies when no date range "
            "is given. Default is 1."
        ),
    )
    parser.add_argument(
        "--start_date",
        type=str,
        default=None,
        metavar="MM/DD/YYYY",
        help=(
            "If provided, only validate records whose `date_modified` field is "
            "on or after this date. Requires --end_date."
        ),
    )
    parser.add_argument(
        "--end_date",
        type=str,
        default=None,
        metavar="MM/DD/YYYY",
        help=(
            "If provided, only validate records whose `date_modified` field is "
            "on or before this date. Requires --start_date."
        ),
    )
    parser.add_argument(
        "--output_csv",
        type=str,
        default=None,
        help=(
            "Path to write the CSV violation report. "
            "Defaults to reports/validation_report_YYYYMMDD_HHMMSS.csv."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = _get_arguments()

    fm_utils.configure_logging(logger)

    if bool(args.start_date) != bool(args.end_date):
        logger.error("--start_date and --end_date must both be provided, or neither.")
        sys.exit(1)

    config = fm_utils.get_config(args.config_file)
    fm_client = fm_utils.initialize_client(config, logger)

    if args.output_csv:
        output_path = Path(args.output_csv)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path("reports") / f"validation_report_{timestamp}.csv"

    # ---- Fetch records ----
    if args.start_date and args.end_date:
        logger.info(
            f"Fetching records modified between {args.start_date} and {args.end_date}."
        )
        records = fm_client.find_all_records(
            query=[{"date_modified": f"{args.start_date}...{args.end_date}"}],
            page_size=args.page_size,
        )
        logger.info(f"Found {len(records)} record(s) in date range.")
    else:
        logger.info("No date range supplied; retrieving all records.")
        records = fm_utils.get_all_records(
            fm_client=fm_client,
            page_size=args.page_size,
            offset=args.offset,
            logger=logger,
        )

    # ---- Validate ----
    all_violations: list[dict] = []
    for record in records:
        all_violations.extend(validate_record(record))

    logger.info(
        f"Processed {len(records)} record(s); "
        f"found {len(all_violations)} violation(s)."
    )

    # ---- Report ----
    _write_csv_report(all_violations, output_path)


if __name__ == "__main__":
    main()
