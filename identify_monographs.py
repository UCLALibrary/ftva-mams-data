import argparse
from get_ftva_alma_data import _get_subfields
import json
import csv
import pymarc
import logging
from datetime import datetime
from pathlib import Path
from pymarc import Record


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alma_holdings_file",
        help="Path to input file containing Alma MMS and Holdings data (JSON)",
        required=True,
    )
    parser.add_argument(
        "--alma_bibs_file",
        help="Path to input file containing Alma bib records (MARC)",
        required=True,
    )
    parser.add_argument(
        "--filemaker_data_file",
        help="Path to input file containing FileMaker data (CSV)",
        required=True,
    )
    parser.add_argument(
        "--output_bib_file",
        help="Path to output file of monograph records only (MARC)",
        required=True,
    )
    parser.add_argument(
        "--manual_review_file",
        help="Path to output file of records requiring manual review (CSV)",
        required=True,
    )
    parser.add_argument(
        "--form_report_file",
        help="Path to output file of report of all forms for each monograph record (CSV)",
        required=True,
    )
    parser.add_argument(
        "--form_mismatch_report_file",
        help="Optional: Path to output file of report of form mismatches (CSV)",
        required=False,
    )
    args = parser.parse_args()
    return args


def _get_logger(name: str | None = None) -> logging.Logger:
    """Returns a logger for this program."""
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


def _dedup_fm_data(fm_data: list) -> list:
    """Deduplicates FileMaker data by inventory number."""
    deduped_fm_data = []
    seen_inventory_numbers = set()
    for record in fm_data:
        if record["inventory_no"] not in seen_inventory_numbers:
            deduped_fm_data.append(record)
            seen_inventory_numbers.add(record["inventory_no"])
    return deduped_fm_data


def _dedup_alma_data(alma_data: list) -> list:
    """Deduplicates Alma data by MMS ID."""
    deduped_alma_data = []
    seen_mms_ids = set()
    for record in alma_data:
        if record["MMS Id"] not in seen_mms_ids:
            deduped_alma_data.append(record)
            seen_mms_ids.add(record["MMS Id"])
    return deduped_alma_data


def _has_fm_production_type(fm_record: dict) -> bool:
    """Given a FileMaker record, checks whether the record has a production type value."""
    production_type = fm_record.get("production_type")
    if production_type:
        return True
    return False


def _get_all_fm_production_types(fm_record: dict) -> list:
    """Given a FileMaker record, returns a list of all production types."""
    production_types = fm_record["production_type"]
    # production types are newline-separated
    production_types = production_types.split("\n")
    return production_types


def _has_non_monograph_fm_production_type(fm_record: dict) -> bool:
    """
    Given a FileMaker record, checks whether the record has a production type value
    indicating a non-monograph type. Returns True if it does, False if it does not.
    """
    non_monograph_types_lowercase = [
        "television series",
        "compilation",
        "mini-series",
        "news",
        "newsreel",
        "newsreels",
        "serials",
        "anthologies",
    ]
    production_types = _get_all_fm_production_types(fm_record)

    # convert production types to lowercase for comparison
    production_types = [type.lower() for type in production_types]
    if any(type in production_types for type in non_monograph_types_lowercase):
        logger.debug(
            f"Non-monograph production type found. "
            f"Production types: {production_types} "
            f"Inventory number: {fm_record['inventory_no']}"
        )
        return True
    return False


def _get_fm_monograph_production_types(fm_record: dict) -> list:
    """Given a FileMaker record, returns a list of production types that are monograph types."""
    monograph_types = [
        "ADVERTISING",
        "ANIMATION",
        "ANTHOLOGIES",
        "CARTOONS",
        "COMMERCIALS",
        "DEMO REELS AND TAPES",
        "DOCUMENTARY",
        "EDUCATIONAL",
        "FEATURE FILM",
        "HOME MOVIES",
        "MADE FOR TV MOVIE",
        "MUSIC VIDEO",
        "SHORT",
        "SPECIALS",
        "STUDENT",
        "TITLES, BKGD, Outs",
        "Titles, background, overlays",
        "Titles, Bkgd, Overlays",
        "TRAILERS AND PROMOS",
        "Trims and Outs",
        "UNEDITED FOOTAGE",
        "VARIETY",
    ]
    production_types = fm_record["production_type"]
    monograph_production_types = []
    for type in monograph_types:
        # check if the monograph type is in the production types string, ignoring case
        if type.lower() in production_types.lower():
            monograph_production_types.append(type)
    logger.debug(
        f"Monograph production types for inventory number {fm_record['inventory_no']}: "
        f"{monograph_production_types}"
    )
    # normalize production types before returning
    normalized_production_types = _normalize_fm_production_types(
        monograph_production_types
    )

    return normalized_production_types


def _normalize_fm_production_types(production_types: list) -> list:
    """
    Given a list of monograph production types, normalizes them to a standard format.
    """
    mapping = {
        "ADVERTISING": "Theater advertising",
        "THEATER ADVERTISING": "Theater advertising",
        "ANIMATION": "Animation",
        "ANTHOLOGIES": "Anthology films",
        "CARTOONS": "Animation",
        "COMMERCIALS": "Commercials",
        "COMPILATION": "Compilations",
        "DEMO REELS AND TAPES": "Demo reels and tapes",
        "DOCUMENTARY": "Documentary",
        "EDUCATIONAL": "Educational",
        "FEATURE FILM": "Feature films",
        "FEATURE FILMS": "Feature films",
        "HOME MOVIES": "Home movies",
        "MADE FOR TV MOVIE": "Made for TV movies",
        "MADE FOR TV MOVIES": "Made for TV movies",
        "MUSIC VIDEO": "Music video",
        "SHORT": "Short films",
        "SHORT FILMS": "Short films",
        "SPECIALS": "Specials",
        "STUDENT": "Student films",
        "STUDENT FILMS": "Student films",
        "TITLES, BKGD, OUTS": "Titles, background, overlays",
        "TITLES, BKGD, OVERLAYS": "Titles, background, overlays",
        "TITLES, BACKGROUND, OVERLAYS": "Titles, background, overlays",
        "TRAILERS AND PROMOS": "Trailers and promos",
        "TRIMS AND OUTS": "Trims and outs",
        "UNEDITED FOOTAGE": "Unedited footage",
        "VARIETY": "Variety",
    }
    normalized_production_types = []
    for type in production_types:
        # normalize case
        type = type.upper()
        if type in mapping:
            normalized_production_types.append(mapping[type])
        else:
            print(f"Unrecognized production type: {type}")
    return normalized_production_types


def _get_all_alma_forms(marc_record: Record) -> list:
    """Given a MARC record, return all Form values."""
    forms = marc_record.get_fields("655")
    form_values = []
    for form in forms:
        # if $2 = local, only use the form "Student films and video"
        if (
            form.get_subfields("2") == ["local"]
            and "Student films and video" in form["a"]
        ):
            # remove ending period, if present
            form_values.append(form["a"].rstrip("."))
        # use all other forms, without end period
        else:
            form_values.append(form["a"].rstrip("."))

    return form_values


def _has_non_monograph_alma_form(marc_record: Record) -> bool:
    """Given a MARC record, checks whether the record has a form value indicating
    a non-monograph type."""
    non_monograph_forms = [
        "Compilations.",
        "Mini-series.",
        "News.",
        "Newsreels.",
        "Serials.",
        "Television mini-series.",
        "Television news programs.",
        "Film serials.",
        "Animated television programs.",
    ]
    forms = _get_subfields(marc_record, "655", "a")
    for form in forms:
        if form in non_monograph_forms:
            logger.debug(
                f"Non-monograph form found for MMS ID {marc_record['001'].data}: "
                f"{form}"
            )
            return True
    # special case for 655 $a Anthologies and 655 $a Short films
    if "Anthologies" in forms and "Short films" in forms:
        return True
    return False


def _get_alma_monograph_forms(alma_record: Record, all_alma_forms: list) -> list:
    """Given a MARC record and a list of forms for that record,
    returns a list of form values that are monograph types."""
    monograph_forms = [
        "Animation",
        "Cartoons",
        "Documentaries and factual films and video",
        "Features",
        "Feature films",
        "Made for TV movies",
        "Shorts",
        "Specials",
        "Animated films",
        "Music shorts",
        "Commercials",
        "Television commercials",
        "Theater advertising",
        "Nonfiction films",
        "Trailers and promo's",
        "Home movies and video",
        "Documentary films",
        "Short films",
        "Public service",
        "Documentary television programs",
    ]
    # local monograph forms - only use these if $2 is "local"
    local_monograph_forms = [
        "Student films and video",
    ]
    monograph_form_values = []
    for form in all_alma_forms:
        if form in monograph_forms or form in local_monograph_forms:
            monograph_form_values.append(form)
    logger.debug(
        f"Monograph forms for MMS ID {alma_record['001'].data}: {monograph_form_values}"
    )
    # normalize form values before returning
    normalized_monograph_forms = _normalize_alma_form_values(monograph_form_values)

    return normalized_monograph_forms


def _normalize_alma_form_values(form_values: list) -> list:
    """Normalizes Alma form values to a standard format."""
    mapping = {
        "Theater advertising": "Advertisements",
        "Animated films": "Animation",
        "Cartoons": "Animation",
        "Commercials": "Television commercials",
        "Documentaries and factual films and video": "Documentary",
        "Features": "Feature films",
        "Student films and video": "Student films",
        "Trailers and promo's": "Trailers and promos",
        "Home movies and video": "Home movies",
        "Documentary films": "Documentary",
        "Public service": "Public service announcements",
        "Documentary television programs": "Documentary",
        "Film trailers": "Trailers and promos",
        "Promos (Television commercials)": "Trailers and promos",
        "Theater commercials (Motion pictures)": "Theater advertising",
        "Promotional film": "Trailers and promos",
        "Promos (Radio commercials)": "Trailers and promos",
        "Shorts": "Short films",
    }
    normalized_form_values = []
    for value in form_values:
        # first, remove ending period, if present
        value = value.rstrip(".")
        if value in mapping:
            normalized_form_values.append(mapping[value])
        else:
            normalized_form_values.append(value)
    return normalized_form_values


def _has_non_monograph_alma_title(marc_record: Record) -> bool:
    """Given a MARC record, checks whether the record has a title value indicating
    a non-monograph type."""
    # if $p or $n is in the title, it's not a monograph
    marc_245 = marc_record.get_fields("245")
    for field in marc_245:
        # check if $p or $n is in the title
        if field.get_subfields("p") or field.get_subfields("n"):
            return True
    # if any 250, 505, or 730 fields are present, it's not a monograph
    if marc_record.get_fields("250", "505", "730"):
        return True
    return False


def _match_records(alma_data: list, fm_data: list) -> list:
    """Matches Alma and FileMaker records based on Alma call number and FM inventory number."""
    fm_data_dict = {fm_record["inventory_no"]: fm_record for fm_record in fm_data}
    matched_records = [
        (alma_record, fm_data_dict[alma_record["Permanent Call Number"]])
        for alma_record in alma_data
        if alma_record["Permanent Call Number"] in fm_data_dict
    ]
    return matched_records


def _get_full_bib_data(matched_data: list, alma_bib_file: str) -> list:
    """Given a list of tuples of Alma data references and FileMaker data, returns a list of
    tuples of full Alma bib data and FileMaker data."""
    with open(alma_bib_file, "rb") as f:
        alma_bib_data = list(pymarc.MARCReader(f))
    alma_bib_dict = {record["001"].data: record for record in alma_bib_data}
    full_data = []
    for alma_data, fm_data in matched_data:
        alma_record = alma_bib_dict.get(alma_data["MMS Id"])
        full_data.append((alma_record, fm_data))
    return full_data


def is_monograph(alma_record: Record, fm_record: dict) -> bool:
    """Given a MARC record and a FileMaker record representing the same item,
    determine whether that item is a monograph."""
    # first, check if the record has a production type in FileMaker
    # if not, proceed to check the Alma record
    if not _has_fm_production_type(fm_record):
        if _has_non_monograph_alma_data(alma_record):
            return False
    # if the record has any production types in FileMaker,
    # check if any FM or Alma forms are non-monograph
    elif _has_non_monograph_fm_production_type(
        fm_record
    ) or _has_non_monograph_alma_data(alma_record):
        return False
    return True


def _has_non_monograph_alma_data(alma_record: Record) -> bool:
    """Given a MARC record, checks the record's Title and Form data to determine if it
    is a non-monograph type."""
    if _has_non_monograph_alma_title(alma_record):
        return True
    if _has_non_monograph_alma_form(alma_record):
        return True
    return False


def get_monograph_forms(alma_record: dict, fm_record: dict) -> dict:
    """For use with monograph records only. Given an Alma record and a FileMaker record,
    returns a dictionary of monograph forms with data sources (Filemaker or Alma) as keys.
    """
    forms = {}
    if _has_fm_production_type(fm_record):
        production_types = _get_fm_monograph_production_types(fm_record)
        forms["filemaker"] = production_types
    all_alma_forms = _get_all_alma_forms(alma_record)
    monograph_forms = _get_alma_monograph_forms(alma_record, all_alma_forms)
    forms["alma"] = monograph_forms
    return forms


def compare_monograph_forms(alma_record: dict, fm_record: dict) -> dict:
    """Compares monograph forms between Alma and FileMaker records."""
    forms = get_monograph_forms(alma_record, fm_record)
    alma_forms = forms.get("alma", [])
    fm_forms = forms.get("filemaker", [])
    common_forms = set(alma_forms).intersection(set(fm_forms))
    unique_alma_forms = set(alma_forms).difference(set(fm_forms))
    unique_fm_forms = set(fm_forms).difference(set(alma_forms))
    comparison = {
        "MMS ID": alma_record["001"].data,
        "common": list(common_forms),
        "unique_alma": list(unique_alma_forms),
        "unique_fm": list(unique_fm_forms),
    }
    return comparison


def has_incompatible_forms(combined_forms: list) -> bool:
    """Given a list of all forms from an Alma record and a FileMaker record,
    checks for incompatible form types."""
    incompatible_types = {"Feature films": ["Shorts", "Short films"]}
    for form in combined_forms:
        if form in incompatible_types:
            for incompatible_type in incompatible_types[form]:
                if incompatible_type in combined_forms:
                    return True
    return False


def reconcile_alma_fm_forms(alma_record: dict, fm_record: dict) -> list:
    """For specified cases, reconcile Alma and Filemaker forms.
    Takes the Alma record and Filemaker record as input, and returns a dictionary
    of reconciled forms."""

    all_alma_forms = _get_all_alma_forms(alma_record)
    monograph_alma_forms = _get_alma_monograph_forms(alma_record, all_alma_forms)
    normalized_alma_forms = _normalize_alma_form_values(monograph_alma_forms)

    monograph_fm_production_types = _get_fm_monograph_production_types(fm_record)
    normalized_fm_production_types = _normalize_fm_production_types(
        monograph_fm_production_types
    )

    combined_forms = normalized_alma_forms + normalized_fm_production_types
    # remove duplicates
    combined_forms = list(set(combined_forms))

    if has_incompatible_forms(combined_forms):
        return ["Incompatible forms"] + combined_forms

    # Where values = “Trailers and promos” OR “Trailers and promo’s” AND “Shorts”, remove “Shorts”.
    if (
        "Trailers and promos" in combined_forms
        or "Trailers and promo's" in combined_forms
    ):
        if "Shorts" in combined_forms:
            combined_forms.remove("Shorts")

    return combined_forms


def _create_reports(
    monograph_records: list,
    form_report_file: str,
    manual_review_file: str,
    form_mismatch_report_file: str | None = None,
) -> None:
    """Assembles and writes reports based on monograph records. Includes a report of all forms
    for each monograph record, a report of records requiring manual review, and an optional report
    of form mismatches between Alma and FileMaker records."""
    form_data = {}
    for alma_record, fm_record in monograph_records:

        forms = reconcile_alma_fm_forms(alma_record, fm_record)
        form_data[(alma_record["001"].data, fm_record["inventory_no"])] = forms

    records_with_incompatible_forms = [
        {
            "MMS ID": record[0],
            "Inventory number": record[1],
            "forms": form_data[record][1:],  # remove "Incompatible forms" prefix
        }
        for record in form_data
        if "Incompatible forms" in form_data[record]
    ]
    print(
        f"Found {len(records_with_incompatible_forms)} records with incompatible forms"
    )
    records_with_no_forms = [
        {
            "MMS ID": record[0],
            "Inventory number": record[1],
            "forms": ["No forms found"],
        }
        for record in form_data
        if not form_data[record]
    ]
    print(f"Found {len(records_with_no_forms)} records with no forms")

    _write_manual_review_report(
        records_with_incompatible_forms, records_with_no_forms, manual_review_file
    )

    # remove records identified for manual review from form_data
    form_data = [
        {"MMS ID": record[0], "Inventory number": record[1], "forms": form_data[record]}
        for record in form_data
        if record[0] not in [r["MMS ID"] for r in records_with_incompatible_forms]
        and record[0] not in [r["MMS ID"] for r in records_with_no_forms]
    ]
    _write_form_report(form_data, form_report_file)

    if form_mismatch_report_file:
        _write_form_mismatch_report(monograph_records, form_mismatch_report_file)


def _write_form_mismatch_report(monograph_records: list, output_file: str) -> None:
    """Writes a form mismatch report to a CSV file."""
    comparison_data = []
    for alma_record, fm_record in monograph_records:
        comparison = compare_monograph_forms(alma_record, fm_record)
        comparison_data.append(comparison)
    # filter to only records with form mismatches
    comparison_data = [
        record
        for record in comparison_data
        if record["unique_alma"] or record["unique_fm"]
    ]
    print(f"Found {len(comparison_data)} records with form mismatches")
    print(f"Writing form mismatch report to {output_file}")
    with open(output_file, "w") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["MMS ID", "common", "unique_alma", "unique_fm"],
        )
        writer.writeheader()
        writer.writerows(comparison_data)


def _write_form_report(form_data: list, output_file: str) -> None:
    """Writes a report of all forms for each monograph record to a CSV file."""
    print(f"Writing form report to {output_file}")
    with open(output_file, "w") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["MMS ID", "Inventory number", "forms"],
        )
        writer.writeheader()
        writer.writerows(form_data)


def _write_manual_review_report(
    records_with_incompatible_forms: list, records_with_no_forms: list, output_file: str
) -> None:
    """Writes a report of records with incompatible forms, or no forms, to a CSV file."""
    print(f"Writing manual review report to {output_file}")
    with open(output_file, "w") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["MMS ID", "Inventory number", "forms"],
        )
        writer.writeheader()
        writer.writerows(records_with_incompatible_forms)
        writer.writerows(records_with_no_forms)


def _write_monograph_records(records: list, output_file: str) -> None:
    """Writes monograph records to a MARC file."""
    print(f"Writing monograph records to {output_file}")
    with open(output_file, "wb") as f:
        for alma_record, fm_record in records:
            f.write(alma_record.as_marc())


def _load_alma_data(alma_data_file: str) -> list:
    """Loads Alma data from a JSON file."""
    with open(alma_data_file) as f:
        alma_data = json.load(f)
    return alma_data


def _load_fm_data(fm_data_file: str) -> list:
    """Loads FileMaker data from a CSV file."""
    with open(fm_data_file) as f:
        fm_data = csv.DictReader(f, fieldnames=["inventory_no", "production_type"])
        fm_data = [row for row in fm_data]
    return fm_data


def main():
    args = _get_args()

    alma_data_refs = _load_alma_data(args.alma_holdings_file)
    fm_data = _load_fm_data(args.filemaker_data_file)
    print(f"Loaded {len(alma_data_refs)} Alma records")
    print(f"Loaded {len(fm_data)} FileMaker records")

    alma_data_refs = _dedup_alma_data(alma_data_refs)
    fm_data = _dedup_fm_data(fm_data)
    print(f"Deduped to {len(alma_data_refs)} Alma records")
    print(f"Deduped to {len(fm_data)} FileMaker records")

    matched_records = _match_records(alma_data_refs, fm_data)
    print(f"Matched {len(matched_records)} records")
    full_matched_records = _get_full_bib_data(matched_records, args.alma_bibs_file)
    print(f"Matched {len(full_matched_records)} full records")

    monograph_records = []
    for alma_record, fm_record in full_matched_records:
        if is_monograph(alma_record, fm_record):
            monograph_records.append((alma_record, fm_record))
    print(f"Found {len(monograph_records)} monograph records")

    _create_reports(
        monograph_records,
        args.form_report_file,
        args.manual_review_file,
        args.form_mismatch_report_file,
    )
    _write_monograph_records(monograph_records, args.output_bib_file)


if __name__ == "__main__":
    logger = _get_logger()
    main()
