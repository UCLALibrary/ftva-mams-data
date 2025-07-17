import argparse
import json
import requests
import xmltodict


def _get_arguments() -> argparse.Namespace:
    """Parse command line arguments.

    :return: Parsed arguments for store_full_data as a Namespace object."""
    parser = argparse.ArgumentParser(
        description="Create a file mapping MARC language code to full name."
    )
    parser.add_argument(
        "--store_full_data",
        help="If specified, save the full set of language data to languages_full_data.json",
        action="store_true",
    )
    return parser.parse_args()


def _get_language_value(language: dict, element_name: str) -> str:
    """Retrieve the value for the given element from the language data.

    :param language: Dictionary of data for one language, as provided by `get_language_data()`.
    :param element_name: String, either "code" or "name". Others are not supported.
    :return: Value associated with the given language element.
    :raises: TypeError, if the retrieved `element_data` is not a string or dictionary.
    :raises: ValueError, if the `element_name` parameter is not a supported value.
    """

    if element_name not in ["code", "name"]:
        raise ValueError(f"Unsupported element: {element_name}")

    # In some cases, the value is in a string (current codes, collective language names)
    # Otherwise, it is in a dictionary of its own under the element_name key.
    element_data = language.get(element_name)
    if not element_data:
        return ""
    if isinstance(element_data, str):
        # String: return it as-is.
        return element_data
    elif isinstance(element_data, dict):
        # Dict: return value for a specific key.
        return element_data.get("#text", "")
    else:
        raise TypeError(f"Unexpected element type for {element_name}: {element_data}")


def _write_json(data: list[dict] | dict, filename: str) -> None:
    """Write processed data to a JSON file.

    :param output_file: Path to the output JSON file.
    :param data: List of dictionaries containing processed metadata.
    `data` can also be a single dictionary, not wrapped in a list."""
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def get_language_data_from_lc(url: str) -> list[dict]:
    """Download XML language data from Library of Congress and
    convert the relevant parts to a more usable format.

    :param url: URL for LC's XML language data.
    :return: List of dictionaries, each containing full data for one language.
    """

    xml = requests.get(url).content
    # Rely on LC to keep a consistent XML structure;
    # if it breaks, we need to revisit this anyhow.
    # Doing this in stages to be explicit, mostly for type checker.
    full_dict = xmltodict.parse(xml)
    # The data is all contained in one element, "codelist".
    code_list: dict = full_dict.get("codelist", {})
    # There are other elements, but we care only about "languages".
    language_dict: dict = code_list.get("languages", {})
    # language_dict now has one key, "language" (yes, singular), containing
    # a list of dictionaries, each with details about one language.
    languages: list[dict] = language_dict.get("language", [])
    return languages


def main() -> None:
    args = _get_arguments()
    # Hard-coded, unless DOGE shuts LC down.
    url = "https://www.loc.gov/standards/codelists/languages.xml"

    language_data = get_language_data_from_lc(url)
    # Create a simple dictionary of code:name for all languages.
    language_map = {
        _get_language_value(language, "code"): _get_language_value(language, "name")
        for language in language_data
    }
    # Sort by code for convenience.
    language_map = {key: language_map[key] for key in sorted(language_map)}

    # Always save this simple map.
    _write_json(language_map, "language_map.json")

    # If requested, also save the full data for other uses.
    if args.store_full_data:
        _write_json(language_data, "languages_full_data.json")


if __name__ == "__main__":
    main()
