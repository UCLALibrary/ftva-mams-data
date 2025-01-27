import argparse
from collections import Counter
import logging
from pprint import pprint
import re
import spacy
import spacy.lang
from csv import DictWriter
from datetime import datetime
from pathlib import Path
from pymarc import MARCReader, Record


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input_file",
        help="Path to input file containing MARC bib records",
        required=True,
    )
    parser.add_argument(
        "--output_file",
        help="Path to output file of parsed data",
        required=True,
    )
    args = parser.parse_args()
    return args


def _get_logger(name: str | None = None) -> logging.Logger:
    """
    Returns a logger for the current application.
    A unique log filename is created using the current time, and log messages
    will use the name in the 'logger' field.
    If name not supplied, the name of the current script is used.
    """
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


def _get_bib_id(record: Record) -> str:
    fld = record.get("001")
    if fld:
        bib_id = fld.data
    else:
        bib_id = None
    return bib_id


def _get_language(record: Record) -> str:
    fld = record.get("008")
    if fld:
        language = fld.data[35:38]
    else:
        language = "###"
    return language


def _get_subfields(record: Record, field_tag: str, subfield_code: str) -> list:
    # field_tag may represent a repeatable field, so get all instances.
    # subfield_code may be repeated within each field, or occur just once per field.
    # Currently, we don't need to maintain the specific field:subfield relationship.
    subfields = []
    fields = record.get_fields(field_tag)
    for field in fields:
        subfields.extend(field.get_subfields(subfield_code))
    return subfields


def _get_single_subfield(record: Record, field_tag: str, subfield_code: str) -> list:
    # Return just the first subfield of any found, as a list to keep a consistent
    # interface with _get_subfields().
    subfields = _get_subfields(record, field_tag, subfield_code)
    if subfields:
        return [subfields[0]]
    else:
        return []


def _get_field_data(record: Record) -> dict:
    bib_id = _get_bib_id(record)
    language = _get_language(record)
    # 245 is not repeatable; 245 $a and $c are not repeatable, but 245 $p is.
    f245a = _get_single_subfield(record, "245", "a")
    f245c = _get_single_subfield(record, "245", "c")
    f245n = _get_subfields(record, "245", "n")
    f245p = _get_subfields(record, "245", "p")
    # 246 is repeatable, though 246 $a is not
    f246a = _get_subfields(record, "246", "a")
    # 250 is repeatable, though 250 $a is not
    f250a = _get_subfields(record, "250", "a")
    # 505 is repeatable; 505 $a is not, but 505 $r is
    f505a = _get_subfields(record, "505", "a")
    f505r = _get_subfields(record, "505", "r")
    field_data = {
        "bib_id": bib_id,
        "language": language,
        "f245a": f245a,
        "f245c": f245c,
        "f245n": f245n,
        "f245p": f245p,
        "f246a": f246a,
        "f250a": f250a,
        "f505a": f505a,
        "f505r": f505r,
        # Directors will be added later.
        "directors": {},
    }
    return field_data


def write_report_to_file(report: list[dict], output_file_name: str) -> None:
    """Writes report to a CSV file, output_file_name."""
    keys = report[0].keys()
    with open(output_file_name, "w") as f:
        writer = DictWriter(f, keys, delimiter="\t")
        writer.writeheader()
        writer.writerows(report)


def get_criteria(record: dict) -> list[str]:
    criteria = []
    f245c_director_count = len(record["directors"]["f245c"])
    f245p_director_count = len(record["directors"]["f245p"])
    # 6.1: Single director in 245 $c, English, plus other stuff.
    if (
        f245c_director_count == 1
        and record["f245a"]
        and not record["f245p"]
        and not record["f250a"]
        and record["language"] == "eng"
    ):
        criteria.append("6.1")

    # 6.2: Single director in 245 $c, NOT English, plus other stuff.
    if (
        f245c_director_count == 1
        and record["f245a"]
        and (record["f250a"] or record["language"] != "eng")
    ):
        criteria.append("6.2")

    # 6.3: Single director in 245 $c, check other 245 subfields.
    if f245c_director_count == 1 and (
        (record["f245a"] and record["f245p"]) or (record["f245a"] and record["f245n"])
    ):
        criteria.append("6.3")

    # 6.4: Multiple directors in 245 $c, plus other stuff.
    if (record["f245a"] and f245c_director_count > 1) or (
        record["f245a"] and (record["f505a"] or record["f505r"])
    ):
        criteria.append("6.4")

    # 6.5: No director in 245 $c.
    if f245c_director_count == 0:
        criteria.append("6.5")

    # 6.6: Director(s?) in 245 $p.
    if f245p_director_count > 0:
        criteria.append("6.6")

    # 6.7: Whatever's left after checking the above.
    # No criteria added already.
    if not criteria:
        criteria.append("6.7")

    return criteria


def _debug_print_leading_director_words(segment: str) -> None:
    # TODO: Remove after debugging, or make the check useful.
    # Find words (alphanumeric strings) and spaces before DIRECTOR.
    pattern = r"[a-zA-Z0-9_ ]+(?=\s+DIRECTOR)"
    matches = re.findall(pattern, segment, re.IGNORECASE)
    if matches:
        print(matches, segment)


def _has_director(segment: str) -> bool:
    wanted = ["directed", "director", "a film by"]
    unwanted = [
        "director of interior photography",
        "exteriors directed by",
        "revue director",
        "staging director",
        "technical director",
        "TV director",
        "television director",
    ]
    # Reject segment if it has any unwanted term.
    for val in unwanted:
        if val in segment:
            return False
    # Still here? Check for wanted terms.
    for val in wanted:
        if val in segment:
            return True
    # Didn't prove there was an acceptable director term.
    return False


def _get_director_segments(subfields: list[str]) -> list[str]:
    """Checks each segment (delimited by ";", if a subfield contains multiple segments)
    of each subfield and returns those which appear to contain information about directors.
    """
    combined = " ".join(subfields)
    segments = [segment.strip() for segment in combined.split(";")]
    return [segment for segment in segments if _has_director(segment)]


def get_names(segments: list[str], model: spacy.Language) -> list[str]:
    """Returns a set of personal names identified by spacy from the
    pre-qualified list of data segments from a MARC record.
    """
    # Use a set to automatically de-duplicate.
    names: set[str] = set()
    for segment in segments:
        doc = model(segment)
        names.update([ent.text for ent in doc.ents if ent.label_ == "PERSON"])

    # If no names were found, despite them being expected in segments, log a message.
    if len(names) == 0:
        logger.warning(f"No names found in {segments}: manual review needed.")
    # TODO: Possibly add other data checks here?

    # Return a list, for better consistency later on.
    return list(names)


def get_bib_data(marc_file: str) -> list[dict]:
    bib_data: list[dict] = []
    with open(marc_file, "rb") as f:
        reader = MARCReader(f)
        for record in reader:
            field_data = _get_field_data(record)
            bib_data.append(field_data)

    logger.info(f"Processed {len(bib_data)} records from {marc_file}")
    return bib_data


def add_director_data(bib_data: list[dict], model: spacy.Language) -> list[dict]:
    """Adds a list of directors' names to each record in bib_data."""
    for record in bib_data:
        # Check 245 $c and $p, though $p currently does not have any director information.
        # We need to know whether directors found in 245 $c or 245 $p (or both).
        for element in ["f245c", "f245p"]:
            subfield_data: list = record[element]
            # Returns empty list if no potential directors found.
            director_segments = _get_director_segments(subfield_data)
            if director_segments:
                directors = get_names(director_segments, model)
            else:
                directors = []
            # record["directors"] was initialized to {} in _get_field_data()
            record["directors"][element] = directors

    return bib_data


def main() -> None:
    args = _get_args()
    model = spacy.load("en_core_web_md")
    # TODO: Consider one call to do these two steps?
    bib_data = get_bib_data(args.input_file)
    bib_data = add_director_data(bib_data, model)

    # For now, check each record here; probably move to method, maybe merge with the above 2?
    criteria_list = []
    for record in bib_data:
        criteria = get_criteria(record)
        c_string = " ".join(criteria)
        criteria_list.append(c_string)
        print(record["bib_id"], criteria)
    d = Counter(criteria_list)
    pprint({key: d[key] for key in sorted(d)})

    # TODO: Helpful during development, probably will remove later;
    # if so, args.output_file may no longer be needed either.
    write_report_to_file(bib_data, args.output_file)


if __name__ == "__main__":
    # Defining logger here makes it available to all code in this module.
    logger = _get_logger()
    # Finally, do everything
    main()
