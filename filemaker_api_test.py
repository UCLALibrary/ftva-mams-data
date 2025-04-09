import argparse
import fmrest
import tomllib


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


def main() -> None:
    """Proof of concept / demo code for basic Filemaker API use.
    See https://github.com/davidhamann/python-fmrest/tree/master/examples
    """
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
    )

    fms.login()

    find_query = [{"inventory_id": "16032"}]  # 1 record
    # find_query = [{"director": "Alan Smithee"}]  # 9 records, currently
    results = fms.find(find_query)

    for rec_number, record in enumerate(results, start=1):
        print(f"===== Data for record number {rec_number} =====")
        # record is not a dict, does not have .items()
        # print(len(record.keys()))
        # print(len(record.values()))
        print(record["portal_Labeling Database_InvID"])
        for key in record.keys():
            value = record[key]
            # Some values have embedded \r... print literally
            print(f"{key} === {repr(value)}")
        print("")


if __name__ == "__main__":
    main()
