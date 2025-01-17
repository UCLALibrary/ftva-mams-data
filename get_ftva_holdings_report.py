import argparse
import tomllib
from csv import DictWriter
from alma_api_client import AlmaAnalyticsClient


def _get_args() -> argparse.Namespace:
    """Returns the command-line arguments for this program."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config_file", help="Path to configuration file", required=True
    )
    parser.add_argument(
        "--output_file",
        help="Path to CSV output file which will be written from report data",
        required=True,
    )
    args = parser.parse_args()
    return args


def _get_config(config_file_name: str) -> dict:
    """Returns configuration for this program, loaded from TOML file."""
    with open(config_file_name, "rb") as f:
        config = tomllib.load(f)
    return config


def get_ftva_holdings_report(analytics_api_key: str, report_path: str) -> list[dict]:
    """Gets the FTVA holdings report data from Alma analytics.
    Path to file is hard-coded.
    """
    aac = AlmaAnalyticsClient(analytics_api_key)
    aac.set_report_path(report_path)
    report = aac.get_report()
    return report


def write_report_to_file(report: list[dict], output_file_name: str) -> None:
    """Writes report to a CSV file, output_file_name."""
    keys = report[0].keys()
    with open(output_file_name, "w") as f:
        writer = DictWriter(f, keys)
        writer.writeheader()
        writer.writerows(report)


def main() -> None:
    args = _get_args()
    config = _get_config(args.config_file)
    analytics_api_key = config["alma_config"]["analytics_api_key"]
    report_path = config["alma_config"]["ftva_holdings_report"]
    report = get_ftva_holdings_report(analytics_api_key, report_path)
    write_report_to_file(report, args.output_file)


if __name__ == "__main__":
    main()
