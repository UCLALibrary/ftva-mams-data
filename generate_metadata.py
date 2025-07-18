import csv
import json
import argparse
import tomllib
import spacy
import logging
import dateutil.parser
from datetime import datetime
from pathlib import Path
from pymarc import Record
from alma_api_client import AlmaAPIClient, get_pymarc_record_from_bib

# for type hinting
from spacy.language import Language


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments for config_file, input_file, and
    output_file as a Namespace object."""
    parser = argparse.ArgumentParser(description="Process metadata for MAMS ingestion.")
    parser.add_argument(
        "--config_file", help="Path to configuration file", required=True
    )
    parser.add_argument(
        "--input_file",
        type=str,
        required=True,
        help="Path to the input CSV file containing record identifiers.",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default="processed_metadata.json",
        required=False,
        help="Path to the output JSON file where processed metadata will be saved.",
    )
    parser.add_argument(
        "--language_map",
        type=str,
        default="language_map.json",
        required=False,
        help="Path to the JSON file containing the code:name language map",
    )
    return parser.parse_args()


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param config_file_name: Path to the configuration file.
    :return: Configuration dictionary."""

    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _get_logger(name: str | None = None) -> logging.Logger:
    """
    Returns a logger for the current application.
    A unique log filename is created using the current time, and log messages
    will use the name in the 'logger' field.

    :param name: Optional name for the logger. If not provided, uses the base filename
    of the current script.
    :return: Configured logger instance."""

    if not name:
        # Use base filename of current script.
        name = Path(__file__).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging_filename = f"{name}_{timestamp}.log"
    logger = logging.getLogger(name)
    logging.basicConfig(
        filename=logging_filename,
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    return logger


def _get_language_map(file_path: str) -> dict:
    """Load the language map from a file.

    :param file_path: Path to the language map file.
    :return: Dictionary with language code:name data.
    """
    with open(file_path, "r") as file:
        return json.load(file)


def _read_input_file(file_path: str) -> list:
    """Read the input CSV file and return a list of dictionaries.

    :param file_path: Path to the input CSV file.
    :return: List of dictionaries representing each row in the CSV file."""
    with open(file_path, mode="r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return [row for row in reader]


def _get_bib_record(client: AlmaAPIClient, mms_id: str) -> Record:
    """Gets a bib record with holding data from Alma API.

    :param client: Alma API client instance.
    :param mms_id: Alma MMS ID for the bib record.
    :return: Pymarc Record object containing the bib data."""
    bib_data: bytes = client.get_bib(mms_id).get("content", b"")
    bib_record = get_pymarc_record_from_bib(bib_data)
    return bib_record


def _get_creator_info_from_bib(bib_record: Record) -> list:
    """Extract creators from the MARC bib record.

    :param bib_record: Pymarc Record object containing the bib data.
    :return: List of strings potentially containing creator names."""
    creators = []
    # MARC 245 $c is not repeatable, so we will always take the first one.
    marc_245_c = (
        bib_record.get_fields("245")[0].get_subfields("c")
        if bib_record.get_fields("245")
        else []
    )

    creators.extend(marc_245_c)
    return creators


def _parse_creators(source_string: str, model: Language) -> list:
    """Given a string sourced from MARC data, parse it to extract creator names.
    First, a list of attribution phrases is checked to see if the string
    contains any of them. If it does, the substring following the phrase
    is processed with a spacy NER model to extract names.

    :param source_string: String containing creator names from MARC data.
    :param model: Spacy language model for NER.
    :return: List of creator names."""

    # Initialize an empty string for the creator string
    creator_string = ""

    attribution_phrases = [
        "directed by",
        "director",  # This will also match "directors"
        "a film by",
        "supervised by",
    ]
    # Find location of the first attribution phrase
    for phrase in attribution_phrases:
        if phrase in source_string.lower():
            start_index = source_string.lower().find(phrase) + len(phrase)
            # Extract substring after the phrase until the end of the string
            # TODO: Does this work in general? Could a director be listed before
            # a non-director role that we shoudn't include?
            creator_string = source_string[start_index:].strip()
            break

    if not creator_string:
        return []

    doc = model(creator_string)
    creators = []
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            creators.append(ent.text)
    return creators


def _get_creators(bib_record: Record, model: Language) -> list:
    """Extract and parse creator names from a MARC bib record.

    :param bib_record: Pymarc Record object containing the bib data.
    :param model: Spacy language model for NER.
    :return: List of parsed creator names."""
    creators = _get_creator_info_from_bib(bib_record)
    parsed_creators = []
    for creator in creators:
        parsed_creators.extend(_parse_creators(creator, model))
    return parsed_creators


def _write_output_file(output_file: str, data: list) -> None:
    """Write processed data to a JSON file.

    :param output_file: Path to the output JSON file.
    :param data: List of dictionaries containing processed metadata."""
    with open(output_file, mode="w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def _get_date_from_bib(bib_record: Record) -> str:
    """Extract the release_broadcast_date from a MARC bib record.

    :param bib_record: Pymarc Record object containing the bib data.
    :return: Publication date as a string, or an empty string if not found."""
    # We want the first MARC 260 $c with both indicators blank.
    date_field = bib_record.get_fields("260")
    if date_field:
        for field in date_field:
            if field.indicator1 == " " and field.indicator2 == " ":
                date_subfield = field.get_subfields("c")
                if date_subfield:
                    return date_subfield[0].strip()
    # If no date found, return an empty string and log a warning.
    logging.warning(f"No publication date found in bib record {bib_record['001']}.")
    return ""


def _parse_date(date_string: str) -> str:
    """Parse a date string into a standardized format.

    :param date_string: Date string to parse.
    :return: Formatted date string or an empty string if parsing fails."""

    # If the date string is in brackets, remove them temporarily
    # Remember this so we can add them back later
    in_brackets = "[" in date_string and "]" in date_string
    if in_brackets:
        date_string = date_string.replace("[", "").replace("]", "")

    # Remove trailing punctuation and whitespace
    date_string = date_string.rstrip(".,;:!?")
    date_string = date_string.strip()

    # Try to parse the date string using dateutil.parser
    # TODO: Add handling for underspecified dates, e.g. "2023" or "April 2023"
    try:
        parsed_date = dateutil.parser.parse(date_string)
        # Format the date as YYYY-MM-DD
        formatted_date = parsed_date.strftime("%Y-%m-%d")
    except (ValueError, dateutil.parser.ParserError) as e:
        # If parsing fails, log the error and return the original string
        logging.info(f"Failed to parse date '{date_string}': {e}")
        formatted_date = date_string

    if in_brackets:
        formatted_date = f"[{formatted_date}]"

    return formatted_date


def _get_date(bib_record: Record) -> str:
    """Extract and format release_broadcast_date from a MARC bib record.

    :param bib_record: Pymarc Record object containing the bib data.
    :return: Formatted date string or an empty string if not found."""
    date_string = _get_date_from_bib(bib_record)
    if not date_string:
        return ""
    return _parse_date(date_string)


def _get_language_code_from_bib(bib_record: Record) -> str:
    """Extract the language code from a MARC bib record.

    :param bib_record: Pymarc Record object containing the bib data.
    :return language_code: The 3-letter MARC language code from the 008/35-37, or an empty string
    if there is no 008 or the 008 is invalid.
    """

    language_code = ""
    # 008 is not repeatable, so .get() instead of .get_fields().
    field_008 = bib_record.get("008")
    if field_008:
        field_data = field_008.data
        # MARC bib 008 should be 40 characters, or is not valid and can't be trusted
        # to have specific values in the correct positions.
        if field_data and len(field_data) == 40:
            # 3 characters, 0-based 35-37
            language_code = field_data[35:38]
        else:
            logging.warning(f"Invalid 008 field in bib record {bib_record['001']}")
    else:
        logging.warning(f"No 008 field found in bib record {bib_record['001']}.")

    return language_code


def _get_language_name(bib_record: Record, language_map: dict) -> str:
    """Get the full name of the language in a MARC bib record.

    :param bib_record: Pymarc Record object containing the bib data.
    :param language_table: Dictionary which maps code:name for supported languages.
    :return language_name: The full name of the language.
    """
    language_code = _get_language_code_from_bib(bib_record)
    language_name = language_map.get(language_code, "")
    if not language_name:
        logging.warning(
            f"No language name found in bib record {bib_record['001']} for {language_code}."
        )
    return language_name


def _get_file_name(item: dict) -> str:
    """Get the file name element from a given item dictionary.

    :param item: Dictionary containing metadata for a record.
    :return: The file name string, or an empty string if not found."""
    file_name = item.get("file_name", "")
    if not file_name:
        logging.warning(
            f"No file name found in item {item.get('alma_bib_id', 'unknown')}."
        )
    return file_name


def _get_folder_name(item: dict) -> str:
    """Get the folder name element from a given item dictionary.

    :param item: Dictionary containing metadata for a record.
    :return: The folder name string, or an empty string if not found."""
    folder_name = item.get("folder_name", "")
    if not folder_name:
        logging.warning(
            f"No folder name found in item {item.get('alma_bib_id', 'unknown')}."
        )
    return folder_name


def _get_file_type(item: dict) -> str:
    """Get the file type element from a given item dictionary.

    :param item: Dictionary containing metadata for a record.
    :return: The file type string, or an empty string if not found."""
    file_type = item.get("file_type", "")
    if not file_type:
        logging.warning(
            f"No file type found in item {item.get('alma_bib_id', 'unknown')}."
        )
    return file_type


def _get_asset_type(item: dict) -> str:
    """Derive the asset type from the item dictionary, based on the file_name.

    :param item: Dictionary containing metadata for a record.
    :return: The asset type string, or an empty string if not found."""
    file_name = _get_file_name(item)
    if not file_name:
        return ""
    lower_file_name = file_name.lower()

    raw_values = ["_raw", "_raw_", "capturefiles", "capturedfiles"]
    if any(raw_value in lower_file_name for raw_value in raw_values):
        return "Raw"
    intermediate_values = ["onelite", "inter", "mti", "raw_mti"]
    if any(
        intermediate_value in lower_file_name
        for intermediate_value in intermediate_values
    ):
        return "Intermediate"

    # Count the number of "final" (including "finals")
    # to determine if it's a final or derivative asset
    final_count = lower_file_name.count("final")
    if final_count == 1:
        return "Final Version"
    elif final_count > 1:
        return "Derivative"

    # If no specific asset type is determined, return an empty string
    return ""


def main() -> None:
    args = _get_arguments()
    config = _get_config(args.config_file)
    api_key = config["alma_config"]["alma_api_key"]
    logger = _get_logger()

    # Read input file
    logger.info(f"Loading input data from {args.input_file}")
    input_data = _read_input_file(args.input_file)
    logger.info(f"Loaded {len(input_data)} records from input file.")

    # Initialize Alma API client
    alma_client = AlmaAPIClient(api_key)

    # Load spacy model for NER
    # TODO: Support use of a custom model, if needed
    nlp_model = spacy.load("en_core_web_md")

    # Load language mapping data.
    language_map = _get_language_map(args.language_map)

    # Process each row in the input data
    processed_data = []
    for row in input_data:
        alma_mms_id = row.get("alma_bib_id")
        bib_record = _get_bib_record(alma_client, alma_mms_id)
        if not bib_record:
            logger.warning(
                f"No bib record found for Alma MMS ID: {alma_mms_id}. Skipping row."
            )
            continue
        # Process each desired field for metadata extraction
        creators = _get_creators(bib_record, nlp_model)
        release_broadcast_date = _get_date(bib_record)
        language_name = _get_language_name(bib_record, language_map)
        file_name = _get_file_name(row)
        # TODO: Add additional metadata fields as needed

        processed_row = {
            "alma_bib_id": alma_mms_id,
            "alma_holdings_id": row.get("alma_holdings_id"),
            "pd_record_id": row.get("pd_record_id"),
            "django_record_id": row.get("django_record_id"),
            "creator": creators,
            "release_broadcast_date": release_broadcast_date,
            "language": language_name,
            "file_name": file_name,
        }

        # Add folder name only for DPX files
        file_type = _get_file_type(row)
        if file_type == "DPX":
            folder_name = _get_folder_name(row)
            if folder_name:
                processed_row["folder_name"] = folder_name

        # Add asset type only if it can be determined
        asset_type = _get_asset_type(row)
        if asset_type:
            processed_row["asset_type"] = asset_type

        processed_data.append(processed_row)

    # Save processed data to output JSON file
    _write_output_file(args.output_file, processed_data)
    logger.info(f"Processed data saved to {args.output_file}")


if __name__ == "__main__":
    main()
