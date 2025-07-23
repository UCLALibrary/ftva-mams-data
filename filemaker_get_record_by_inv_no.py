import argparse
import fmrest
from fmrest import Server
from fmrest.record import Record
from fmrest.exceptions import FileMakerError
import json
import tomllib

# Figured this might be useful elsewhere
# so declaring globally here
FM_FIELD_SUBSET = (
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
)


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


def get_filemaker_record_by_inventory_number(
    fms: Server, inventory_number: str
) -> Record | None:
    """Given an inventory number sourced from the DL Django application,
    get the matching record from Filemaker via the API.

    :param fms Server: Server instance with authenticated session.
    :param str inventory_number: The inventory number with which to query Filemaker.
    :return: Record instance representing matched record, or None if not found.
    """
    # Use Filemaker syntax for exact match (==) in query
    query = [{"inventory_no": f"=={inventory_number}"}]

    try:
        # Date format defaults to US format (MM-DD-YYYY);
        # setting to ISO-8601 (YYYY-MM-DD) instead.
        foundset = fms.find(query, date_format="iso-8601")
        found_count = len(list(foundset))
        if found_count and found_count > 1:
            # Using FileMakerError to raise a custom message here
            # if multiple records are returned
            raise FileMakerError(
                error_code=None,
                error_message=f"Multiple records returned for inventory number {inventory_number}",
            )
        return foundset[0]
    except FileMakerError as error:
        print(f"An error occurred: {error}")
        return None


def _subset_filemaker_record(fm_record: Record) -> str:
    """Subsets a Filemaker Record based on the configured subset of fields.

    :param Record fm_record: A fmrest Record instance.
    :return: A JSON string representing the subset of the Filemaker data.
    """
    output_dict = {
        field: fm_record[field]
        for field in FM_FIELD_SUBSET
        if field in fm_record.to_dict()
    }
    return json.dumps(output_dict, indent=4)


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

    matching_record = get_filemaker_record_by_inventory_number(
        fms, args.inventory_number
    )
    if matching_record:
        print(_subset_filemaker_record(matching_record))


if __name__ == "__main__":
    main()
