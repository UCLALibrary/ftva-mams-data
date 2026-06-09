import argparse
import csv
import logging
import sys
from collections.abc import Callable  # for type hinting validator functions
from datetime import datetime
from pathlib import Path

from fmrest.record import Record

import filemaker_utils as fm_utils

# Use module-level logger.
logger = logging.getLogger(Path(__file__).stem)


# ---------------------------------------------------------------------------
# Output and Metadata Constants
# ---------------------------------------------------------------------------

# Output columns for CSV report.
REPORT_FIELDNAMES = [
    "inventory_id",
    "inventory_no",
    "field",
    "user_last_modified",
    "date_modified",
    "violation",
]

# Per-layout field name differences for the standard output columns.
# This allows the validation logic to refer to these fields by a consistent name
# (e.g. "inventory_id", "date_modified") even though the actual field names vary by layout.
LAYOUT_METADATA: dict[str, dict[str, str]] = {
    "InventoryForLabeling_API": {
        "inventory_id_field": "inventory_id",
        "inventory_no_field": "inventory_no",
        "user_last_modified_field": "user_last_modified",
        "date_modified_field": "date_modified",
    },
    "NEW DIGITAL_API": {
        "inventory_id_field": "inventory_id",
        "inventory_no_field": "inventory_no",
        "user_last_modified_field": "user_last_modified",
        "date_modified_field": "date_modified",
    },
    "NEW DIGITAL STORAGE_API": {
        "inventory_id_field": "Inventory_id_fk",
        "inventory_no_field": "Inventory_no_fk",
        "user_last_modified_field": "ModifiedBy",
        "date_modified_field": "ModificationTimestamp",
    },
}

# Portal name on NEW DIGITAL_API (DC layout) that contains Digital Media fields (item-level data).
DC_PORTAL = "portal_Portal_DM_Items"

# For NEW DIGITAL_API (DC layout), fields in the portal are accessed using this prefix.
DC_PORTAL_PREFIX = "Digital Media_Item Unit::"

# Portal name on NEW DIGITAL STORAGE_API (DS layout) that contains carrier fields (file path/size).
DS_PORTAL = "portal_pDMUnit"

# For NEW DIGITAL STORAGE_API (DS layout), fields in the portal are accessed using this prefix.
DS_PORTAL_PREFIX = "Digital Media_carrier::"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_null(value: str) -> bool:
    """Return True if value is empty or whitespace-only."""
    return not value or not value.strip()


def _get_field(record: Record, name: str) -> str:
    """Return a flat field value from a record as a stripped string, or '' if absent."""
    try:
        return str(record[name] or "").strip()
    except (KeyError, AttributeError):
        return ""


def _get_portal_field(portal_record: Record, bare_name: str, prefix: str) -> str:
    """Return a field value from a portal row record.

    FileMaker portal rows store fields as 'TableOccurrence::fieldName'.
    This helper accepts the bare field name and prepends the prefix.
    """
    return _get_field(portal_record, f"{prefix}{bare_name}")


def _make_violation(
    layout: str,
    record: Record,
    field: str,
    message: str,
    portal_record_id: str = "",
) -> dict:
    """Build a violation dict for use in the output report CSV.

    :param layout: FM layout name.
    :param record: The top-level fmrest Record.
    :param field: The field name (may include portal prefix for portal fields).
    :param message: Human-readable description of the violation.
    """
    metadata = LAYOUT_METADATA[layout]
    return {
        "record_id": record.record_id,
        "portal_record_id": portal_record_id,
        "inventory_id": _get_field(record, metadata["inventory_id_field"]),
        "inventory_no": _get_field(record, metadata["inventory_no_field"]),
        "user_last_modified": _get_field(record, metadata["user_last_modified_field"]),
        "date_modified": _get_field(record, metadata["date_modified_field"]),
        "field": field,
        "violation": message,
    }


# ---------------------------------------------------------------------------
# Single-field validators
# ---------------------------------------------------------------------------


def _check_null(value: str) -> list[str]:
    """Field must not be null / empty."""
    if _is_null(value):
        return ["Field is null or empty."]
    return []


# ---------------------------------------------------------------------------
# Layout -> flat field -> validators mapping
# ---------------------------------------------------------------------------
# Fields that live directly on the record (not in portals).
# For now, each field has only a single validator (_check_null),
# but using a list for each field allows us to add more if needed.

LAYOUT_VALIDATORS: dict[str, dict[str, list[Callable]]] = {
    # Analog GE Form layout
    "InventoryForLabeling_API": {
        "production_type": [_check_null],  # cross-field rule also applies
        "Language": [_check_null],
        "donor_code": [_check_null],
        "Acquisition type": [_check_null],
        "type": [_check_null],
        "item_unit_holdings": [_check_null],
        "title": [_check_null],
        "date_received": [_check_null],
        "director": [_check_null],
        "release_broadcast_year": [_check_null],  # cross-field rule also applies
        "format": [_check_null],
        "inventory_no": [_check_null],
    },
    # NDM Digital Carrier layout
    "NEW DIGITAL_API": {
        # Fields shared with GE layout
        "production_type": [_check_null],  # cross-field rule also applies
        "Language": [_check_null],
        "donor_code": [_check_null],
        "Acquisition type": [_check_null],
        "type": [_check_null],
        "item_unit_holdings": [_check_null],
        "title": [_check_null],
        "date_received": [_check_null],
        "director": [_check_null],
        "release_broadcast_year": [_check_null],  # cross-field rule also applies
        # DC-only flat fields
        "retention_status": [_check_null],  # cross-field rule also applies
        "asset_type": [_check_null],
        # sound_format(1): conditional only; see _check_cross_field_rules
        # Item_unit_number, file_size, Creation_date, audio_class, file_path:
        #   found in portal_Portal_DM_Items; see PORTAL_FIELD_VALIDATORS below
    },
    # NDM Digital Storage Format layout
    "NEW DIGITAL STORAGE_API": {
        # file_path and file_size are in portal_pDMUnit; see PORTAL_FIELD_VALIDATORS.
        "Barcode": [_check_null],
        "Location": [_check_null],
    },
}


# ---------------------------------------------------------------------------
# Portal field -> validators mapping
# ---------------------------------------------------------------------------
# Fields that live inside FileMaker portals.

PORTAL_FIELD_VALIDATORS: dict[str, dict[str, list[Callable]]] = {
    DC_PORTAL: {
        "Item_unit_number": [_check_null],
        "file_size_display": [_check_null],
        "Creation_date": [_check_null],
        "audio_class": [_check_null],
        "file_path": [_check_null],
    },
    DS_PORTAL: {
        "file_path": [_check_null],
        "file_size": [_check_null],
    },
}

# Which layouts have which portals, and the prefix for each portal's fields.
# Used by _check_portal_fields() to iterate and access portal rows.
LAYOUT_PORTALS: dict[str, list[tuple[str, str]]] = {
    "NEW DIGITAL_API": [(DC_PORTAL, DC_PORTAL_PREFIX)],
    "NEW DIGITAL STORAGE_API": [(DS_PORTAL, DS_PORTAL_PREFIX)],
}

# The FM layout parameter alone cannot be trusted to return only the expected
# record type -- both GE and DC layouts return a mix of analog and digital
# records from the same underlying table. The digital_record field distinguishes
# them: "0" = legacy/analog (GE), "1" = NDM digital (DC).
# The DS layout is a separate table so no filter is needed.
LAYOUT_DIGITAL_RECORD_FILTER: dict[str, str | None] = {
    "InventoryForLabeling_API": "0",
    "NEW DIGITAL_API": "1",
    "NEW DIGITAL STORAGE_API": None,
}


# ---------------------------------------------------------------------------
# Portal field validation
# ---------------------------------------------------------------------------


def _check_portal_fields(layout: str, record: Record) -> list[dict]:
    """Validate fields inside portal rows for the given layout and record."""
    violations = []
    portals = LAYOUT_PORTALS.get(layout, [])

    for portal_name, prefix in portals:
        field_validators = PORTAL_FIELD_VALIDATORS.get(portal_name, {})
        if not field_validators:
            continue

        portal_foundset = record[portal_name]
        rows = list(portal_foundset)

        if not rows:
            logger.debug(
                f"[{layout}] Portal {portal_name!r} is empty on "
                f"record_id={record.record_id}; skipping portal checks."
            )
            continue

        for portal_row in rows:
            portal_record_id = str(_get_field(portal_row, "recordId"))
            for bare_name, validators in field_validators.items():
                value = _get_portal_field(portal_row, bare_name, prefix)
                for validator in validators:
                    for message in validator(value):
                        # Use the bare field name in the field column and include
                        # the portal row id in the violation dict for logging only.
                        field_label = bare_name
                        v = _make_violation(
                            layout, record, field_label, message, portal_record_id
                        )
                        violations.append(v)

    return violations


# ---------------------------------------------------------------------------
# Cross-field conditional rules
# ---------------------------------------------------------------------------


def _check_cross_field_rules(layout: str, record: Record) -> list[dict]:
    """Check rules that depend on the value of more than one field.

    Rules by layout:

    GE and DC layouts:
      1. Where production_type = "TELEVISION SERIES", flag if episode no. or
         episode_title are null.
      2. Where release_broadcast_year = "N/A" or "Unknown", flag if record_date
         is null.

    DC layout only:
      3. Where retention_status = "Temporary", flag if retention_start_date or
         retention_end_date are null.
      4. Where object_purpose = "Preservation (Full)" or "Access (Core)", flag
         if sound_format(1) is null.

    DS layout: no cross-field rules currently defined.
    """
    violations = []

    # Rules 1 and 2 apply to both GE and DC layouts.
    if layout in ("InventoryForLabeling_API", "NEW DIGITAL_API"):

        # Rule 1: TELEVISION SERIES requires episode fields.
        production_type = _get_field(record, "production_type")
        if production_type.upper() == "TELEVISION SERIES":
            for ep_field in ("episode no.", "episode_title"):
                if _is_null(_get_field(record, ep_field)):
                    violations.append(
                        _make_violation(
                            layout,
                            record,
                            ep_field,
                            f"{ep_field} is null but production_type is "
                            f"'TELEVISION SERIES'.",
                        )
                    )

        # Rule 2: N/A or Unknown release_broadcast_year requires record_date.
        release_year = _get_field(record, "release_broadcast_year")
        if release_year.upper() in ("N/A", "UNKNOWN"):
            if _is_null(_get_field(record, "record_date")):
                violations.append(
                    _make_violation(
                        layout,
                        record,
                        "record_date",
                        f"record_date is null but release_broadcast_year is "
                        f"{release_year!r}.",
                    )
                )

    # Rules 3 and 4 apply to DC layout only.
    if layout == "NEW DIGITAL_API":

        # Rule 3: Temporary retention requires start and end dates.
        retention_status = _get_field(record, "retention_status")
        if retention_status.upper() == "TEMPORARY":
            for date_field in ("retention_start_date", "retention_end_date"):
                if _is_null(_get_field(record, date_field)):
                    violations.append(
                        _make_violation(
                            layout,
                            record,
                            date_field,
                            f"{date_field} is null but retention_status is "
                            f"'Temporary'.",
                        )
                    )

        # Rule 4: Preservation/access records require sound_format.
        OBJECT_PURPOSES_REQUIRING_SOUND = ["PRESERVATION (FULL)", "ACCESS (CORE)"]
        object_purpose = _get_field(record, "object_purpose")
        if object_purpose.upper() in OBJECT_PURPOSES_REQUIRING_SOUND:
            if _is_null(_get_field(record, "sound_format(1)")):
                violations.append(
                    _make_violation(
                        layout,
                        record,
                        "sound_format(1)",
                        f"sound_format(1) is null but object_purpose is "
                        f"{object_purpose!r}.",
                    )
                )

    return violations


# ---------------------------------------------------------------------------
# Per-record validation logic
# ---------------------------------------------------------------------------


def validate_record(layout: str, record: Record) -> list[dict]:
    """Run all validation checks against the given record for the specified layout.

    Runs:
      1. Single-field null checks from LAYOUT_VALIDATORS[layout].
      2. Portal field null checks from _check_portal_fields().
      3. Cross-field conditional rules from _check_cross_field_rules().
    Returns a list of violation dicts suitable for output to the report CSV.
    """
    violations = []
    record_dict = record.to_dict()

    # 1. Single-field (flat) checks
    for field_name, validators in LAYOUT_VALIDATORS.get(layout, {}).items():
        if field_name not in record_dict:
            logger.debug(
                f"[{layout}] Field {field_name!r} not on record "
                f"{record.record_id}; skipping."
            )
            continue
        value = str(record[field_name] or "")
        for validator in validators:
            for message in validator(value):
                v = _make_violation(layout, record, field_name, message)
                violations.append(v)
                logger.debug(
                    f"VIOLATION [{layout}] record_id={record.record_id} "
                    f"inventory_id={v['inventory_id']!r} "
                    f"field={field_name!r}: {message}"
                )

    # 2. Portal field checks
    for v in _check_portal_fields(layout, record):
        violations.append(v)
        logger.debug(
            f"VIOLATION (portal) [{layout}] record_id={record.record_id} "
            f"portal_record_id={v.get('portal_record_id', '')!r} "
            f"field={v['field']!r}: {v['violation']}"
        )

    # 3. Cross-field rules
    for v in _check_cross_field_rules(layout, record):
        violations.append(v)
        logger.debug(
            f"VIOLATION (cross-field) [{layout}] record_id={record.record_id} "
            f"inventory_id={v['inventory_id']!r} "
            f"field={v['field']!r}: {v['violation']}"
        )

    return violations


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


def _write_csv_report(violations: list[dict], output_path: Path) -> None:
    """Write violations dicts to a CSV file at the given path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        # Ignore extra dict keys (like 'portal_record_id') so we can keep
        # that value for logging without forcing it into the CSV.
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(violations)
    logger.info(f"Report written to {output_path} ({len(violations)} violation(s)).")


# ---------------------------------------------------------------------------
# Record retrieval
# ---------------------------------------------------------------------------


def _build_query_criterion(
    layout: str,
    date_field: str,
    start_date: str | None,
    end_date: str | None,
) -> dict | None:
    """Build the FileMaker find query criterion dict for the given layout and args.

    Returns a dict suitable for use as a single find criterion, or None if no
    find query is needed.

    AND conditions within a find request are expressed by putting multiple
    field-value pairs in the same dict. The digital_record filter is always
    included for GE and DC layouts, combined with the date range if provided.
    """
    digital_record_filter = LAYOUT_DIGITAL_RECORD_FILTER[layout]
    criterion: dict = {}

    if start_date and end_date:
        criterion[date_field] = f"{start_date}...{end_date}"

    if digital_record_filter is not None:
        criterion["digital_record"] = digital_record_filter

    return criterion if criterion else None


def _get_records_for_layout(
    config: dict,
    layout: str,
    args: argparse.Namespace,
) -> list[Record]:
    """Initialize a client for the given layout and fetch records."""
    logger.info(f"Connecting to layout: {layout!r}.")
    fm_client = fm_utils.initialize_client(config, logger, layout=layout)
    meta = LAYOUT_METADATA[layout]
    date_field = meta["date_modified_field"]

    query_criterion = _build_query_criterion(
        layout, date_field, args.start_date, args.end_date
    )

    if query_criterion is not None:
        logger.info(
            f"[{layout}] Fetching records with query filter criteria: {query_criterion}."
        )
        records = fm_client.find_all_records(
            query=[query_criterion],
            page_size=args.page_size,
        )
    else:
        # DS layout with no date range: no find criteria, iterate all records.
        logger.info(f"[{layout}] Fetching all records (no query filter criteria).")
        records = fm_utils.get_all_records(
            fm_client=fm_client,
            page_size=args.page_size,
            offset=args.offset,
            logger=logger,
        )

    logger.info(f"[{layout}] {len(records)} record(s) retrieved.")
    return records


# ---------------------------------------------------------------------------
# CLI arguments
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
            "If provided, only validate records modified on or after this date. "
            "The field used for filtering varies by layout (see LAYOUT_METADATA). "
            "Requires --end_date."
        ),
    )
    parser.add_argument(
        "--end_date",
        type=str,
        default=None,
        metavar="MM/DD/YYYY",
        help=(
            "If provided, only validate records modified on or before this date. "
            "Requires --start_date."
        ),
    )
    parser.add_argument(
        "--layout",
        type=str,
        required=True,
        choices=list(LAYOUT_VALIDATORS.keys()),
        help=(
            "FileMaker layout to validate. Must be one of: "
            + ", ".join(LAYOUT_VALIDATORS.keys())
            + "."
        ),
    )
    parser.add_argument(
        "--output_csv",
        type=str,
        default=None,
        help=(
            "Path to write the CSV violation report. "
            "Defaults to reports/validation_report_{LAYOUT}_{YYYYMMDD_HHMMSS}.csv."
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

    layout = args.layout
    logger.info(f"Validating layout: {layout!r}.")

    if args.output_csv:
        output_path = Path(args.output_csv)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize layout name for use in a filename (replace spaces with underscores).
        layout_slug = layout.replace(" ", "_")
        output_path = (
            Path("reports") / f"validation_report_{layout_slug}_{timestamp}.csv"
        )

    # ---- Fetch records ----
    records = _get_records_for_layout(config, layout, args)

    # ---- Validate ----
    all_violations: list[dict] = []
    for record in records:
        all_violations.extend(validate_record(layout, record))

    logger.info(
        f"Processed {len(records)} record(s); " f"{len(all_violations)} violation(s)."
    )

    # ---- Report ----
    _write_csv_report(all_violations, output_path)


if __name__ == "__main__":
    main()
