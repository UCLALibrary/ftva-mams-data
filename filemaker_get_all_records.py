import argparse
import fmrest
from fmrest.record import Record
import json
import tomllib
from datetime import datetime


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file",
        help="Path to config file with Filemaker connection info",
        required=True,
    )
    args = parser.parse_args()
    return args


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file."""
    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def _write_json(data: list[dict], filename_base: str = "filemaker_data") -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_base}_{timestamp}.json"
    with open(filename, "w") as f:
        json.dump(data, f)


def main() -> None:
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
        timeout=60,  # enough for 5000 records startup
    )

    fms.login()

    # Can't find a way to get this via API, other than maybe
    # iterating until failure?  Client shows 606_110 as of 20250416.
    total_records = 700_000
    # Initial fetch is quite slow, about 30 seconds for first 100,
    # but subsquent batches of 100 take less than 1 second each.
    # 250 takes 26 seconds + 1.5 seconds
    # 500 takes 30 seconds + 1.8 seconds
    # 1000 takes 33 seconds + 3.1 seconds
    # 2500 takes 33 seconds and 7.0 seconds
    # 5000 takes 42 seconds + 14 seconds
    limit = 2500
    start = 1

    all_records = []
    fm_record: Record  # for typehints
    while start <= total_records:
        print(datetime.now())
        print(f"Getting {limit} records starting at {start}...")
        try:
            results = fms.get_records(offset=start, limit=limit)
            print(datetime.now())
            current_batch = []
            for rec_number, fm_record in enumerate(results, start=start):
                # For now, ignore the "portal" fields, which are of
                # type fmrest.foundset.Foundset and contain 0-many other records.
                # The only relevant field is "portal_Labeling Database_InvID".
                record = fm_record.to_dict(ignore_portals=True)
                current_batch.append(record)
            all_records.extend(current_batch)
            start += limit
        except fmrest.exceptions.FileMakerError:
            # This is thrown when there are no more records to fetch in a fresh
            # batch (start aka offset is greater than the real number of records).
            # No more records, so break out of the while loop.
            break

    _write_json(all_records)
    print("DONE:", datetime.now())


if __name__ == "__main__":
    main()
