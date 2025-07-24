import argparse
import tomllib
import requests
import json
import xmltodict


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program.

    :return: Parsed CLI arguments.
    """

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config_file",
        help="Path to config file with Alma connection info",
        required=True,
    )

    parser.add_argument(
        "--call_number",
        help="Call number of record to match between the DL Django app and Alma",
        required=True,
    )

    args = parser.parse_args()

    return args


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file.

    :param str config_file_name: Filename for the TOML-format config file.
    :return: A dict with the config info.
    """

    with open(config_file_name, "rb") as f:

        config = tomllib.load(f)

    return config


def get_alma_data_by_call_number(sru_url: str, call_number: str) -> dict:
    """Fetches Alma data for a given call number.

    :param sru_url: Base URL for the Alma SRU API.
    :param call_number: Call number to search in Alma.
    :return: dictionary containing all data from original XML response.
    """

    alma_url_parameters = (
        "?version=1.2&operation=searchRetrieve&recordSchema=marcxml"
        "&query=alma.PermanentCallNumber="
    )
    # If the call number contains spaces, wrap the call number in quotes
    if " " in call_number:
        call_number = f'"{call_number}"'
    full_sru_url = f"{sru_url}{alma_url_parameters}{call_number}"

    response = requests.get(full_sru_url)

    if response.status_code != 200:
        raise Exception(f"Error fetching data from Alma: {response.text}")

    # Convert XML response to a dictionary
    xml_dict = xmltodict.parse(response.text)
    return xml_dict


def get_relevant_fields_alma(alma_data: dict) -> list:
    """Extracts only the relevant fields from the Alma data.

    :param alma_data: The full Alma data dictionary, as obtained from the SRU API,
        assumed to contain only one record.
    :return: A list of relevant fields extracted from the Alma data.
    """
    # SearchRetrieveResponse is the top-level key in the Alma SRU response
    if "searchRetrieveResponse" not in alma_data:
        return []

    # Assuming there is only one record in the response, this is the expected structure
    record = (
        alma_data["searchRetrieveResponse"]
        .get("records", {})
        .get("record", [])
        .get("recordData", {})
        .get("record", [])
    )
    # If there are multiple records in the response, there will be multiple obects
    # in the topmost "record" list, i.e.:
    # all_records = alma_data["searchRetrieveResponse"].get("records", {}).get("record", [])
    # for item in all_records:
    #     record = item.get("recordData", {}).get("record", [])

    # Relevant MARC fields to extract, defined by FTVA
    relevant_field_tags = ["001", "008", "245", "246", "260", "655"]
    relevant_fields = []

    # Relevant fields are both control fields and data fields
    control_fields = record.get("controlfield", [])
    data_fields = record.get("datafield", [])
    all_fields = control_fields + data_fields

    for field in all_fields:
        if isinstance(field, dict) and field.get("@tag") in relevant_field_tags:
            relevant_fields.append(field)

    return relevant_fields


def main() -> None:
    args = _get_args()
    config = _get_config(args.config_file)
    alma_config = config.get("alma_config", {})
    alma_sru_url = alma_config.get("alma_sru_url", "")

    alma_data = get_alma_data_by_call_number(alma_sru_url, args.call_number)

    number_of_records = int(
        alma_data.get("searchRetrieveResponse", {}).get("numberOfRecords", 0)
    )

    if number_of_records == 0:
        print(f"No records found for call number {args.call_number}")
    elif number_of_records > 1:
        print(
            f"Multiple ({number_of_records}) records found for call number "
            f"{args.call_number}"
        )
    else:
        print(f"Single record found for call number {args.call_number}")
        relevant_fields = get_relevant_fields_alma(alma_data)
        print(f"Relevant fields: {json.dumps(relevant_fields, indent=4)}")


if __name__ == "__main__":
    main()
