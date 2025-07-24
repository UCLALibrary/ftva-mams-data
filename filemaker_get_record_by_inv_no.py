import argparse
import fmrest
from fmrest import Server
from fmrest.record import Record
from fmrest.exceptions import FileMakerError
import json
import tomllib

# Figured this might be useful elsewhere
# so declaring globally here
FM_PREVIEW_FIELDS = [
    "type",
    "inventory_no",
    "inventory_id",
    "format_type",
    "title",
    "aka",
    "director",
    "episode_title",
    "production_type",
    "Acquisition type",
    "Alma",
    "availability",
    "release_broadcast_year",
    "notes",
    "element_info",
    "spac",
    "episode no.",
    "film base",
    "donor_code",
]


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program.

    :return: Parsed CLI arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file",
        help="Path to config file with Filemaker connection info",
        required=True,
    )
    parser.add_argument(
        "--inventory_number",
        help="Inventory number of record to match between the DL Django app and Filemaker",
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


def get_filemaker_records_by_inventory_number(
    fms: Server, inventory_number: str
) -> list:
    """Given an inventory number sourced from the DL Django application,
    get the matching record from Filemaker via the API.

    :param fms Server: Server instance with authenticated session.
    :param str inventory_number: The inventory number with which to query Filemaker.
    :return: A list with 0 or more Records.
    """
    # Use Filemaker syntax for exact match (==) in query
    query = [{"inventory_no": f"=={inventory_number}"}]

    try:
        # `fms.find()` raises an exception if no records are found for query,
        # rather than simply returning an empty `Foundset`--hence the `try` block.
        # Also the date format in `fms.find()` defaults to US format (MM-DD-YYYY);
        # setting it to ISO-8601 (YYYY-MM-DD) instead.
        foundset = fms.find(query, date_format="iso-8601")
        # If no exception is raised, then foundset has 1 or more records.
        # Return it as a list to be consistent with empty list returned if no records found.
        return list(foundset)
    except FileMakerError as error:
        # FileMakerError doesn't provide the error code as an integer,
        # but rather as a string message, so check the string for
        # error 401, which represents "no records found".
        # See Filemaker error codes @https://help.claris.com/en/pro-help/content/error-codes.html
        error_message = error.args[0]  # error message is first item in `args` tuple
        if "error 401" in error_message:
            return []  # if no records found, return an empty list
        # Re-raise the error if it's something other than 401--no records found
        raise error


def _get_specific_fields(
    fm_record: Record, specific_fields: list[str] = FM_PREVIEW_FIELDS
) -> dict:
    """Gets the provided specific fields from a Filemaker Record instance.

    :param Record fm_record: A fmrest Record instance.
    :param list[str] specific_fields: A list of specific fields to get from the Record.
    (Default: `FM_PREVIEW_FIELDS`)
    :return: A dict with the specific fields from the Filemaker Record.
    Fields are only included if they exist in the Record.
    """
    return {
        field: fm_record[field]
        for field in specific_fields
        if field in fm_record.to_dict()
    }


def main() -> None:
    """Entry-point for this program."""

    args = _get_args()
    config = _get_config(args.config_file)

    fm_config = config["filemaker"]
    fms = fmrest.Server(
        url=fm_config["url"],
        user=fm_config["user"],
        password=fm_config["password"],
        database=fm_config["database"],
        layout=fm_config["layout"],
        api_version=fm_config["api_version"],
        timeout=120,
        # 60 seconds should be enough for 5000 records startup;
        # double it to be safe.
    )
    fms.login()

    matching_records = get_filemaker_records_by_inventory_number(
        fms, args.inventory_number
    )
    if not matching_records:
        print(f"No records found for inventory number {args.inventory_number}")
    elif len(matching_records) == 1:  # if 1 record returned, print it as JSON
        record_dict = _get_specific_fields(matching_records[0])
        record_json = json.dumps(record_dict, indent=4)
        print(f"Single record found for inventory number {args.inventory_number}:")
        print(record_json)
    else:
        print(
            f"Multiple ({len(matching_records)}) records"
            f" found for inventory number {args.inventory_number}"
        )


if __name__ == "__main__":
    main()
