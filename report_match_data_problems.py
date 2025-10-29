import json
import csv
import tomllib
import argparse
import logging
from pathlib import Path
from strsimpy.normalized_levenshtein import NormalizedLevenshtein
from pymarc import Record
from datetime import datetime, timedelta
from ftva_etl.metadata.marc import _get_date_from_bib
from alma_api_client import AlmaAPIClient, BibRecord


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments for config_file and input files (Alma, Digital Data, and
    Filemaker) as a Namespace object."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file",
        help="Path to configuration file with API credentials (for Alma data retrieval).",
        required=True,
    )
    parser.add_argument(
        "--alma_file",
        type=str,
        required=True,
        help="""Path to the input CSV file containing Alma data,
         as produced by get_ftva_holdings_report.py.""",
    )
    parser.add_argument(
        "--digital_data_file",
        type=str,
        required=True,
        help="""Path to the input JSON file containing Digital Data records,
         as produced by digital_data_get_all_records.py.""",
    )
    parser.add_argument(
        "--filemaker_file",
        type=str,
        required=True,
        help="""Path to the input JSON file containing FileMaker records,
         as produced by filemaker_get_all_records.py.""",
    )
    return parser.parse_args()


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary."""

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _configure_logger(name: str | None = None):
    """Returns a logger for the current application.
    A unique log filename is created using the current time, and log messages
    will use the name in the 'logger' field.

    :param name: Optional name for the logger. If not provided, uses the base filename
    of the current script.
    :return: Configured logger instance."""

    if not name:
        # Use base filename of current script.
        name = Path(__file__).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging_file = Path("logs", f"{name}_{timestamp}.log")  # Log to `logs/` dir
    logging_file.parent.mkdir(parents=True, exist_ok=True)  # Make `logs/` dir, if none
    logging.basicConfig(
        filename=logging_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )


def read_json_file(file_path: str) -> list[dict]:
    """Read a JSON file and return its content as a list of dictionaries.

    :param file_path: Path to the JSON file.
    :return: List of dictionaries representing the JSON data.
    """

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def read_csv_file(file_path: str) -> list[dict]:
    """Read a CSV file and return its content as a list of dictionaries.
    :param file_path: Path to the CSV file.
    :return: List of dictionaries representing the CSV data.
    """

    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = [row for row in reader]
    return data


def data_is_recent(digital_data_filename: str, filemaker_filename: str) -> bool:
    """Check if the data files are recent based on timestamps in filenames.

    :param digital_data_filename: Filename of the Digital Data file.
    :param filemaker_filename: Filename of the FileMaker data file.
    :return: True if DD and Filemaker data is recent (within 1 day), False otherwise.
    """

    # Filemaker and Digital Data files have timestamps in the filename, i.e.
    # digital_data_YYYYMMDD_HHMMSS.json
    # filemaker_data_YYYYMMDD_HHMMSS.json
    json_timestamp_format = "%Y%m%d_%H%M%S"
    digital_data_timestamp_str = (
        digital_data_filename.split("_")[-2]
        + "_"
        + digital_data_filename.split("_")[-1].split(".")[0]
    )
    filemaker_timestamp_str = (
        filemaker_filename.split("_")[-2]
        + "_"
        + filemaker_filename.split("_")[-1].split(".")[0]
    )

    digital_data_timestamp = datetime.strptime(
        digital_data_timestamp_str, json_timestamp_format
    )
    filemaker_timestamp = datetime.strptime(
        filemaker_timestamp_str, json_timestamp_format
    )
    now = datetime.now()
    one_day_ago = now - timedelta(days=1)
    if digital_data_timestamp >= one_day_ago and filemaker_timestamp >= one_day_ago:
        return True
    return False


def has_no_008(record: Record) -> str:
    """Check if a MARC record has no 008 field.

    :param record: The MARC record to check.
    :return: "Yes" if the record has no 008 field, empty string otherwise.
    """

    field_008 = record.get_fields("008")
    if not field_008:
        return "Yes"
    return ""


def invalid_language(record: Record, valid_language_codes: set[str]) -> str:
    """Check if a MARC record has an invalid language code in field 008.

    :param record: The MARC record to check.
    :return: String representing the invalid language code status. "BLANK" if blank,
    "TOO SHORT" if too short, the invalid code itself if invalid, empty string otherwise.
    """

    field_008 = record.get_fields("008")
    if not field_008:
        return ""

    # Safely get the raw 008 data; Field.data may be None or shorter than expected.
    raw_data = getattr(field_008[0], "data", "") or ""
    if len(raw_data) < 38:
        # If the field is entirely blank or only whitespace, treat as BLANK,
        # otherwise treat as TOO SHORT so callers can distinguish.
        if raw_data.strip() == "":
            return "BLANK"
        return "TOO SHORT"

    lang_code = raw_data[35:38]
    if lang_code == "   ":
        return "BLANK"
    elif len(lang_code) < 3:
        return "TOO SHORT"
    if lang_code not in valid_language_codes:
        return lang_code
    return ""


def no_26x_date(record: Record) -> str:
    """Check if a MARC record has no valid 26x date, using _get_date_from_bib.

    :param record: The MARC record to check.
    :return: "Yes" if no date is found in 26x fields, empty string otherwise.
    """

    date = _get_date_from_bib(record)
    # no date is represented as {"date": "", "qualifier": ""}
    if date["date"] == "" and date["qualifier"] == "":
        return "Yes"
    return ""


def lacks_attribution_phrase(record: Record) -> str:
    """Check if a MARC record lacks a relevant statement of responsibility in 245 $c.

    :param record: The MARC record to check.
    :return: "Yes" if no relevant attribution phrase is found, empty string otherwise.
    """

    field_245 = record.get_fields("245")[0]  # only one 245 field per record
    if not field_245:
        return "Yes"
    attribution_phrases = [
        "directed by",
        "director",
        "directors",
        "a film by",
        "supervised by",
    ]
    subfield_c = field_245.get_subfields("c")
    if not subfield_c:
        return "Yes"
    for phrase in attribution_phrases:
        if phrase in subfield_c[0].lower():  # $c is not repeatable
            return ""
    return "Yes"


def get_alma_title(record: Record) -> str:
    """Get the title from a MARC record from 245 $a only, removing trailing punctuation
    and moving leading articles to the end.

    :param record: The MARC record to extract the title from.
    :return: The title string if found, empty string otherwise.
    """

    field_245 = record.get_fields("245")
    if field_245:
        field = field_245[0]
        title = field["a"] if "a" in field else ""

        # Remove trailing punctuation
        title = title.rstrip(" /:;,.")
        # Safely obtain indicators (may be None or contain None values, according to type checker)
        indicators = getattr(field, "indicators", None) or ["", ""]
        article_index = (
            indicators[1] if len(indicators) > 1 and indicators[1] is not None else ""
        )

        if article_index in ["0", "_", ""]:  # No non-filing characters
            return title.strip()

        try:
            non_filing_chars = int(article_index)
        except (ValueError, TypeError):
            # If indicator is not a valid integer, treat as no non-filing characters
            return title.strip()

        if non_filing_chars > 0 and len(title) > non_filing_chars:
            # Move leading article to end
            leading_article = title[:non_filing_chars].strip()
            main_title = title[non_filing_chars:].strip()
            title = f"{main_title}, {leading_article}"
            return title.strip()
    return ""


def get_filemaker_title(fm_record: dict) -> str:
    """Get the title from a FileMaker record.

    :param fm_record: The FileMaker record dictionary.
    :return: The title string if found, empty string otherwise.
    """

    title = fm_record.get("title", "")
    return title.strip()


def get_title_match_score(
    alma_record: Record, fm_record: dict, levenshtein: NormalizedLevenshtein
) -> float:
    """Calculate the normalized Levenshtein similarity score between
    the title in a MARC record and a FileMaker record, using provided
    NormalizedLevenshtein instance.

    :param alma_record: The MARC record to extract the title from.
    :param fm_record: The FileMaker record dictionary.
    :param levenshtein: An instance of NormalizedLevenshtein to use for similarity calculation.
    :return: The normalized Levenshtein similarity score between the two titles.
    """

    alma_title = get_alma_title(alma_record)
    fm_title = get_filemaker_title(fm_record)
    if not alma_title or not fm_title:
        return 0
    score = levenshtein.similarity(alma_title, fm_title)
    return score


def get_valid_language_codes() -> set[str]:
    """Read the valid language codes from the language_map.json file.

    :return: Set of valid language codes.
    """

    with open("language_map.json", "r", encoding="utf-8") as f:
        language_map = json.load(f)
    return set(language_map.keys())


def build_inventory_index(
    records: list[dict],
    field: str,
    inv_no_prefixes: list[str],
    call_no_suffixes: list[str],
) -> dict[str, dict]:
    """Pre-index records by plausible inventory number variants.

    This replicates the logic of _is_inventory_number_match():
    - exact matches always included
    - plus variants with suffixes, but only if the value starts with an approved prefix

    :param records: List of record dictionaries to index.
    :param field: The field name in the record dictionaries to use as inventory number.
    :param inv_no_prefixes: List of inventory number prefixes to consider for suffix variants.
    :param call_no_suffixes: List of call number suffixes to append for variant generation
    :return: Dictionary mapping inventory number variants to their corresponding record.
    """
    index = {}
    for r in records:
        value = (r.get(field) or "").strip()
        if not value:
            continue

        # Always index the raw value
        index[value] = r

        if call_no_suffixes:
            # Add suffix variants only if prefix matches known patterns
            if any(value.startswith(prefix) for prefix in inv_no_prefixes):
                for suffix in call_no_suffixes:
                    index[value + suffix] = r

    return index


def find_inventory_number_match(
    digital_data_record: dict,
    fm_index: dict,
    alma_index: dict,
) -> dict:
    """For the given digital data record, find if there is exactly one matching
    FileMaker record and Alma record based on inventory number.

    :param digital_data_record: The digital data record dictionary to use.
    :param fm_index: Pre-indexed FileMaker records by inventory number variants.
    :param alma_index: Pre-indexed Alma records by inventory number variants.
    :param call_no_suffixes: List of call number suffixes to consider for matching in Alma.
    :return: Dictionary with keys 'fm_record' and 'alma_record' for the matched records,
    with None values if no match is found.
    """
    digital_inventory_number = digital_data_record.get("inventory_number", "").strip()
    if not digital_inventory_number:
        return {"fm_record": None, "alma_record": None}

    fm_matches = []
    alma_matches = []
    # Start with Alma records, as there are fewer
    alma_record = alma_index.get(digital_inventory_number)
    if alma_record:
        alma_matches.append(alma_record)

    # If we don't have exactly one Alma match, return no match
    if len(alma_matches) != 1:
        return {"fm_record": None, "alma_record": None}

    # If we do have exactly one Alma match, proceed to find FileMaker matches
    alma_record = alma_matches[0]

    fm_record = fm_index.get(digital_inventory_number)
    if fm_record:
        fm_matches.append(fm_record)

    # If we have exactly one FileMaker match and one Alma match, return them
    if len(fm_matches) == 1:
        fm_record = fm_matches[0]
        return {"fm_record": fm_record, "alma_record": alma_record}

    # No unique match found
    return {"fm_record": None, "alma_record": None}


def report_data_match_issues(
    alma_record: BibRecord,
    fm_record: dict,
    dd_record: dict,
    valid_language_codes: set[str],
) -> dict:
    """Generate a list of data match issues between Alma, FileMaker, and Digital Data records.

    :param alma_record: The MARC BibRecord from Alma.
    :param fm_record: The FileMaker record dictionary.
    :param dd_record: The Digital Data record dictionary.
    :param valid_language_codes: Set of valid language codes for checking field 008.
    :return: Dict with information about data match issues, to use for CSV construction.
    """

    marc_record = alma_record.marc_record
    # Safely extract Alma bib id and guard against None/missing fields
    # (to appease type checker)
    alma_bib_id = ""
    if marc_record and getattr(marc_record, "get_fields", None):
        fields_001 = marc_record.get_fields("001")
        if fields_001:
            field_001 = fields_001[0]
            alma_bib_id = getattr(field_001, "data", "") or ""

    # Construct NormalizedLevenshtein instance once for efficiency
    levenshtein = NormalizedLevenshtein()
    data = {
        "Alma bib id": alma_bib_id,
        "FileMaker Record ID": fm_record.get("recordId", "") if fm_record else "",
        "Digital Data Inventory Number": (
            dd_record.get("inventory_number", "") if dd_record else ""
        ),
        "No 008 field": has_no_008(marc_record) if marc_record else "",
        "Invalid language": (
            invalid_language(marc_record, valid_language_codes) if marc_record else ""
        ),
        "No 26x date": no_26x_date(marc_record) if marc_record else "",
        "Lacks attribution phrase": (
            lacks_attribution_phrase(marc_record) if marc_record else ""
        ),
        "Title match score": (
            get_title_match_score(marc_record, fm_record, levenshtein)
            if marc_record and fm_record
            else 0
        ),
        "Alma title": get_alma_title(marc_record) if marc_record else "",
        "Filemaker title": get_filemaker_title(fm_record) if fm_record else "",
    }
    return data


def main():
    args = _get_arguments()
    config = _get_config(args.config_file)
    _configure_logger()

    print(
        "Retrieving 1-1-1 matches and finding data problems...\n"
        "see logs/ for more details."
    )

    if not data_is_recent(args.digital_data_file, args.filemaker_file):
        logging.error(
            "One or more input data files are not recent (produced in last 24 hours). Exiting."
        )
        return
    logging.info(
        "All input data files are recent. Proceeding with data match issue report."
    )

    alma_data = read_csv_file(args.alma_file)
    digital_data = read_json_file(args.digital_data_file)
    filemaker_data = read_json_file(args.filemaker_file)

    dd_record_count = len(digital_data)
    logging.info(
        f"Loaded {dd_record_count} Digital Data records, "
        f"{len(alma_data)} Alma records, "
        f"and {len(filemaker_data)} FileMaker records."
    )

    alma_client = AlmaAPIClient(config["alma_config"]["alma_api_key"])
    logging.info("Initialized Alma API client.")

    valid_language_codes = get_valid_language_codes()
    logging.info(
        "Loaded valid language codes for MARC field 008 checking from language_map.json."
    )

    # Constants for call number suffixes and inventory number prefixes
    CALL_NO_SUFFIXES = [" M", " R", " T"]
    INV_NO_PREFIXES = ["DVD", "HFA", "VA", "VD", "XFE", "XFF", "XVE", "ZVB"]

    # Pre-index FileMaker and Alma records by inventory number variants
    alma_index = build_inventory_index(
        alma_data, "Permanent Call Number", INV_NO_PREFIXES, CALL_NO_SUFFIXES
    )
    fm_index = build_inventory_index(
        filemaker_data, "inventory_no", INV_NO_PREFIXES, []  # No suffixes for FM
    )
    logging.info("Pre-indexed Alma and FileMaker records by inventory number variants.")

    output_rows = []
    seen_inventory_numbers = set()
    for i, dd_record in enumerate(digital_data, start=1):

        # Log progress every 5%
        if i % max(1, dd_record_count // 20) == 0:
            progress_percent = (i / dd_record_count) * 100
            logging.info(
                f"Processing DD records: {i}/{dd_record_count} ({progress_percent:.1f}%) completed."
            )

        # Skip records with empty inventory number
        if dd_record.get("inventory_number", "") == "":
            continue
        # Skip records with an inventory number already found in output_rows
        inv_num = dd_record.get("inventory_number", "").strip()
        if not inv_num or inv_num in seen_inventory_numbers:
            continue
        seen_inventory_numbers.add(inv_num)

        # Find matching FileMaker and Alma records
        match = find_inventory_number_match(dd_record, fm_index, alma_index)
        fm_record = match["fm_record"]
        alma_record_dict = match["alma_record"]

        # If no unique match found, skip
        if not fm_record or not alma_record_dict:
            continue

        # Get full Record from Alma using API client
        alma_record = alma_client.get_bib_record(alma_record_dict["MMS Id"])
        issues = report_data_match_issues(
            alma_record, fm_record, dd_record, valid_language_codes
        )
        output_rows.append(issues)

    # Write output to CSV
    output_fieldnames = [
        "Alma bib id",
        "FileMaker Record ID",
        "Digital Data Inventory Number",
        "No 008 field",
        "Invalid language",
        "No 26x date",
        "Lacks attribution phrase",
        "Title match score",
        "Alma title",
        "Filemaker title",
    ]
    with open(
        "data_match_issues_report.csv", "w", newline="", encoding="utf-8"
    ) as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=output_fieldnames)
        writer.writeheader()
        for row in output_rows:
            writer.writerow(row)


if __name__ == "__main__":
    main()
