import argparse
import json
import logging
import re
import spacy
import spacy.lang
from collections import Counter
from csv import DictWriter
from datetime import datetime
from pathlib import Path
from pymarc import MARCReader, Record
from pprint import pprint  # TODO: Remove after debugging
from spacy_utils import train_model


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
    parser.add_argument(
        "--training_file",
        help="Path to file of corrected names for training spacy",
        required=False,
    )
    parser.add_argument(
        "--dump_criteria",
        help="Dump all assigned criteria for each record to all_criteria.txt, for debugging",
        required=False,
        action="store_true",
    )
    parser.add_argument(
        "--dump_directors",
        help="Dump all director segments and names to alL_directors.txt, for debugging",
        required=False,
        action="store_true",
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
    """Returns the bibliographic id of the MARC record."""
    fld = record.get("001")
    if fld:
        bib_id = fld.data
    else:
        bib_id = None
    return bib_id


def _get_language(record: Record) -> str:
    """Returns the primary language code of the MARC record."""
    fld = record.get("008")
    if fld:
        language = fld.data[35:38]
    else:
        language = "###"
    return language


def _get_subfields(record: Record, field_tag: str, subfield_code: str) -> list:
    """Returns a list of subfield values from the MARC record.
    field_tag may represent a repeatable field, so get all instances.
    subfield_code may be repeated within each field, or occur just once per field.
    Does not maintain the specific field:subfield relationship.
    """
    subfields = []
    fields = record.get_fields(field_tag)
    for field in fields:
        subfields.extend(field.get_subfields(subfield_code))
    return subfields


def _get_single_subfield(record: Record, field_tag: str, subfield_code: str) -> list:
    """Returns just the first subfield of any found, as a list to keep a consistent
    interface with _get_subfields().
    """
    subfields = _get_subfields(record, field_tag, subfield_code)
    if subfields:
        return [subfields[0]]
    else:
        return []


def _get_field_data(record: Record) -> dict:
    """Returns a dictionary of specific data from the MARC bib record. Currently
    this is only what's needed for evaluating criteria for categorization.
    """
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
    }
    return field_data


def _dump_all_criteria(bib_data: list[dict]) -> None:
    """Prints all criteria satisfied for each record.
    Useful for debugging.
    """
    with open("all_criteria.txt", "w") as f:
        criteria_list = []
        for record in bib_data:
            criteria = _get_all_criteria(record)
            c_string = ", ".join(criteria)
            criteria_list.append(c_string)
            f.write(f"{record["bib_id"]} -> {c_string}\n")
    # Also print counts to stdout, without writing them to file.
    print("\nCounts of criteria combinations")
    print("===============================")
    d = Counter(criteria_list)
    pprint({key: d[key] for key in sorted(d)})


def _dump_directors(bib_data: list[dict]) -> None:
    """Dumps all director information to hard-coded file.
    Useful for debugging.
    """
    with open("all_directors.txt", "w") as f:
        for record in bib_data:
            # We can trust these keys to exist, though they may be empty.
            for subfield_code in ["f245c", "f245p"]:
                if record["directors"][subfield_code]:
                    f.write(
                        f"{subfield_code} -> {record[subfield_code]} -> "
                        f"{record["directors"][subfield_code]}\n"
                    )


def get_criteria(record: dict) -> str:
    """Categorizes record against the criteria in 6.x of the Criteria Matrix.
    Returns the first matching criterion.
    """
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
        return "6.1"

    # 6.2: Single director in 245 $c, NOT English, plus other stuff.
    if (
        f245c_director_count == 1
        and record["f245a"]
        and (record["f250a"] or record["language"] != "eng")
    ):
        return "6.2"

    # 6.3: Single director in 245 $c, check other 245 subfields.
    if f245c_director_count == 1 and (
        (record["f245a"] and record["f245p"]) or (record["f245a"] and record["f245n"])
    ):
        return "6.3"

    # 6.4: Multiple directors in 245 $c, English, plus other stuff.
    # TODO: Thelma still reviewing, uncomment / change as needed.
    if (
        f245c_director_count > 1
        and record["f245a"]
        and not record["f250a"]
        and record["language"] == "eng"
    ):
        return "6.4"

    # 6.5: Multiple directors in 245 $c, NOT English, plus other stuff.
    if (
        f245c_director_count > 1
        and record["f245a"]
        and (record["f250a"] or record["language"] != "eng")
    ):
        return "6.5"

    # 6.6: Multiple directors in 245 $c, check other 245 subfields.
    if f245c_director_count > 1 and (
        (record["f245a"] and record["f245p"]) or (record["f245a"] and record["f245n"])
    ):
        return "6.6"

    # 6.7: No director in 245 $c.
    if f245c_director_count == 0:
        return "6.7"

    # 6.8: Director(s?) in 245 $p.
    if f245p_director_count > 0:
        return "6.8"

    # 6.9: Whatever's left after checking the above.
    # No criteria matched already.
    return "6.9"


def _get_all_criteria(record: dict) -> list[str]:
    # TODO: Remove after debugging.
    """Categorizes record against the criteria in 6.x of the Criteria Matrix.
    Returns a list of all matching criteria, for debugging / review only.
    """
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

    # 6.4: Multiple directors in 245 $c, English, plus other stuff.
    # TODO: Thelma still reviewing, uncomment / change as needed.
    if (
        f245c_director_count > 1
        and record["f245a"]
        and not record["f250a"]
        and record["language"] == "eng"
    ):
        criteria.append("6.4")

    # 6.5: Multiple directors in 245 $c, NOT English, plus other stuff.
    if (
        f245c_director_count > 1
        and record["f245a"]
        and (record["f250a"] or record["language"] != "eng")
    ):
        criteria.append("6.5")

    # 6.6: Multiple directors in 245 $c, check other 245 subfields.
    if f245c_director_count > 1 and (
        (record["f245a"] and record["f245p"]) or (record["f245a"] and record["f245n"])
    ):
        criteria.append("6.6")

    # 6.7: No director in 245 $c.
    if f245c_director_count == 0:
        criteria.append("6.7")

    # 6.8: Director(s?) in 245 $p.
    if f245p_director_count > 0:
        criteria.append("6.8")

    # 6.9: Whatever's left after checking the above.
    # No criteria matched already.
    if not criteria:
        criteria.append("6.9")

    return criteria


def _debug_print_leading_director_words(segment: str) -> None:
    # TODO: Remove after debugging, or make the check useful.
    # Find words (alphanumeric strings) and spaces before DIRECTOR.
    pattern = r"[a-zA-Z0-9_ ]+(?=\s+DIRECTOR)"
    matches = re.findall(pattern, segment, re.IGNORECASE)
    if matches:
        print(matches, segment)


def _has_director(segment: str) -> bool:
    """Determines whether segment (a piece of text extracted from MARC data)
    should contain a director's name, based on the presence and/or absence of
    certain words.
    """
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


def _fix_name_suffix(names: list[str]) -> list[str]:
    """Fixes specific case where a single person's name has had the 'Jr.'
    suffix incorrectly identified as a separate 'name'.
    If more general cases are found, this should be re-implemented
    via spaCy (re)training.
    """
    # This currently is the only suffix being handled.
    suffix = "Jr."

    # Caller should have done this, but be sure.
    if len(names) != 2 or suffix not in names:
        raise ValueError(f"Unable to handle name and {suffix}: {names}")

    # Order of values in names is not guaranteed, but one value will be "Jr."
    # and one will not.  Remove "Jr." and take the remaining value.
    # Must be done in 2 steps, since list.remove() always returns None.
    names.remove(suffix)
    main_name = names[0]

    # Return the single now-combined name as a list to maintain expected interface.
    return [f"{main_name}, {suffix}"]


def get_names(segments: list[str], model: spacy.Language) -> list[str]:
    """Returns a set of personal names identified by spacy from the
    pre-qualified list of data segments from a MARC record.
    """
    # Use a set to automatically de-duplicate.
    names: set[str] = set()
    for segment in segments:
        doc = model(segment)
        names.update([ent.text for ent in doc.ents if ent.label_ == "PERSON"])

    # Convert set to list, for better consistency with other data later on.
    names = list(names)

    # If no names were found, despite them being expected in segments, log a message.
    if len(names) == 0:
        logger.warning(f"No names found in {segments}: manual review needed.")

    # spacy model does not handle "Jr." correctly - possibly others.
    # TODO: Handle these via log and (re)training the model?
    if len(names) == 2 and "Jr." in names:
        names = _fix_name_suffix(names)

    # TODO: Possibly add other data checks here?

    return names


def get_bib_data(marc_file: str, model: spacy.Language) -> list[dict]:
    """Returns a list of data extracted from a file of binary MARC bibliographic
    records.  The relevant data for each record is in a dictionary created by
    _get_field_data().
    """
    bib_data: list[dict] = []
    with open(marc_file, "rb") as f:
        reader = MARCReader(f)
        for record in reader:
            field_data = _get_field_data(record)
            # Add director information, derived from field_data.
            field_data["directors"] = get_director_data(field_data, model)
            # TODO: Temporary, for exploration / demo only.
            # Add original MARC record for quick reference along with parsed data.
            field_data["marc"] = record

            bib_data.append(field_data)

    logger.info(f"Processed {len(bib_data)} records from {marc_file}")
    return bib_data


def get_director_data(field_data: dict, model: spacy.Language) -> dict[str, list]:
    """Returns a dictionary of lists of directors' names based on elements of field_data,
    using the given model to identify personal name entities.
    """
    # Check 245 $c and $p, though $p currently does not have any director information.
    # We need to know whether directors found in 245 $c or 245 $p (or both).
    director_data = {}
    for element in ["f245c", "f245p"]:
        subfield_data: list = field_data[element]
        # Returns empty list if no potential directors found.
        director_segments = _get_director_segments(subfield_data)
        if director_segments:
            directors = get_names(director_segments, model)
        else:
            directors = []
        director_data[element] = directors

    return director_data


def write_data_to_file(report: list[dict], output_file_name: str) -> None:
    """Writes data to a CSV file, output_file_name."""
    keys = report[0].keys()
    with open(output_file_name, "w") as f:
        writer = DictWriter(f, keys, delimiter="\t")
        writer.writeheader()
        writer.writerows(report)


def get_mams_json(record: dict) -> dict:
    # All temporary for exploration.
    # Data still needs to be cleaned / transformed.
    # MARC extraction very hacky for now.
    bib_record: Record = record["marc"]
    # Comments for each element:
    # tag_no:subfield_code:field_repeatable:subfield_repeatable (within each field).
    # Source: https://www.loc.gov/marc/bibliographic/

    # 245:a:N:N
    title = _get_single_subfield(bib_record, "245", "a")
    # 246:a:Y:N
    alternative_titles = _get_subfields(bib_record, "246", "a")
    # 245:p:N:Y
    episode_titles = _get_subfields(bib_record, "245", "p")
    # 245:a:N:N SAME AS TITLE
    series_title = _get_single_subfield(bib_record, "245", "a")
    # 490 and/or 830 (no other spec given)
    # 490 and 830 are both repeatable; subfields vary
    subseries_titles = [fld.value() for fld in bib_record.get_fields("490", "830")]
    # 245:n:N:Y
    episode_numbers_245 = _get_subfields(bib_record, "245", "n")
    # 246:n:Y:Y
    episode_numbers_246 = _get_subfields(bib_record, "246", "n")
    # From 008, already obtained
    language = record["language"]
    # 041 (no other spec given); repeatable, with many repeatable subfields
    language_other = [fld.value() for fld in bib_record.get_fields("041")]
    # Already obtained from 245 $c and possibly $p; flatten into single list
    directors = [name for lst in record["directors"].values() for name in lst]
    # broadcast_date: too broadly defined
    # production_date: too broadly defined
    # release_date: too broadly defined
    # From 001, already obtained - for debugging, at least
    alma_bib_id = record["bib_id"]

    # For now, throw everything into a flat dictionary for json output later.
    mams_data = {
        "alma_bib_id": alma_bib_id,
        "title": title,
        "alternative_titles": alternative_titles,
        "episode_titles": episode_titles,
        "series_title": series_title,
        "subseries_titles": subseries_titles,
        "episode_numbers_245": episode_numbers_245,
        "episode_numbers_246": episode_numbers_246,
        "language": language,
        "language_other": language_other,
        "directors": directors,
    }

    # Many keys will have empty lists for values, if there was no MARC data for them;
    # remove those and return what's left.
    return {key: val for key, val in mams_data.items() if val}


def main() -> None:
    args = _get_args()
    model = spacy.load("en_core_web_md")
    # Apply our local changes, if requested.
    if args.training_file:
        model = train_model(args.training_file, model)

    # Get all the Alma data we'll need from MARC input file,
    # using the spacy model to identify personal names.
    bib_data = get_bib_data(args.input_file, model)

    # TODO: Something useful with this... currently just shows usage.
    # Waiting for clarity on why evaluating criteria matters for output.
    # for record in bib_data:
    #     criteria = get_criteria(record)
    #     print(record["bib_id"], criteria)

    # Useful during debugging
    if args.dump_directors:
        _dump_directors(bib_data)
    if args.dump_criteria:
        _dump_all_criteria(bib_data)

    # TODO: Helpful during development, probably will remove later;
    # if so, args.output_file may no longer be needed either.
    write_data_to_file(bib_data, args.output_file)

    # TODO: Organize output in json
    # Assuming this should be list of records, and not wrapped in a root element of some sort.
    all_mams_records = []
    for record in bib_data:
        # For now, use original record temporarily added in get_bib_data()
        mams_json = get_mams_json(record)
        all_mams_records.append(mams_json)

    with open("ftva_mams_data.json", "w") as json_file:
        json.dump(all_mams_records, json_file, indent=2)


if __name__ == "__main__":
    # Defining logger here makes it available to all code in this module.
    logger = _get_logger()
    # Finally, do everything
    main()
