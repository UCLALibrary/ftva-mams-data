import argparse

# import json
import pickle
import re
import spacy
from csv import DictWriter
from pprint import pprint
from pymarc import MARCReader, Record
import spacy.lang


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


def print_stats(data: list) -> None:
    # Quick list of unique 245 $p, which currently has up to 2 values
    print("f245p values:")
    print("==================")
    values = [row["f245p"] for row in data]
    unique_values = list(map(pickle.loads, dict.fromkeys(map(pickle.dumps, values))))
    pprint(unique_values, width=132)
    print("==================")

    # Quick check of list sizes
    for key, value in data[0].items():
        if isinstance(value, list):
            print(f"Max values in {key}: ", max([len(row[key]) for row in data]))


def write_report_to_file(report: list[dict], output_file_name: str) -> None:
    """Writes report to a CSV file, output_file_name."""
    keys = report[0].keys()
    with open(output_file_name, "w") as f:
        writer = DictWriter(f, keys, delimiter="\t")
        writer.writeheader()
        writer.writerows(report)


def characterize_record():
    pass


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


def _has_multiple_directors(record: dict) -> bool:
    """Returns True if a record has more than 1 director, False otherwise."""
    directors: dict = record["directors"]
    # This should contain multiple keys, one for each record element in which
    # director(s) were found. Each key has a list of directors, which may be empty.
    director_count = sum([len(value) for value in directors.values()])
    return director_count > 1


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
    # Return it as a list, for better consistency later on.
    return list(names)


def get_bib_data(marc_file: str) -> list[dict]:
    bib_data: list[dict] = []
    with open(marc_file, "rb") as f:
        reader = MARCReader(f)
        for record in reader:
            field_data = _get_field_data(record)
            bib_data.append(field_data)
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
    bib_data = get_bib_data(args.input_file)

    # Helpful during development
    write_report_to_file(bib_data, args.output_file)

    # Helpful during development
    # print_stats(bib_data)

    bib_data = add_director_data(bib_data, model)


if __name__ == "__main__":
    main()
