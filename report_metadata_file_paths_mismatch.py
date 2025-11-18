import json
import argparse
import pandas as pd
from pathlib import Path


def _get_arguments() -> argparse.Namespace:
    """Returns the command-line arguments for this program.

    :return: Parsed arguments as a Namespace object.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file_lists",
        type=str,
        nargs="+",
        required=True,
        help="Text files with lists of file paths existing on disk, one per line.",
    )
    parser.add_argument(
        "--metadata_files",
        type=str,
        nargs="+",
        required=True,
        help="JSON files containing metadata records, as output by `generate_metadata.py`.",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        required=False,
        help="Name of the output file to write the report to, under the `output/` directory.",
        default="filename_mismatches.xlsx",
    )
    return parser.parse_args()


def _get_metadata_assets(metadata_files: list[str]) -> list[dict]:
    """Read a list of metadata files and return a list of asset records.

    :param metadata_files: List of paths to the metadata files.
    :return: List of asset records.
    """

    asset_records = []
    for metadata_file in metadata_files:
        with open(metadata_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Data should be available at `data["media"]["assets"]`
            asset_records.extend(data["media"]["assets"])
    return asset_records


def _get_file_paths(file_lists: list[str]) -> list[str]:
    """Read a list of file list files and return a list of file paths.

    :param file_lists: List of paths to the file list files.
    :return: List of file paths.
    """

    file_paths = []
    for file_list in file_lists:
        with open(file_list, "r", encoding="utf-8") as f:
            file_paths.extend([line.strip() for line in f.readlines()])
    return file_paths


def _write_report(
    in_file_list_not_in_metadata: list[str],
    in_metadata_not_in_file_list: list[str],
    output_file: str,
) -> None:
    """Write a report of filename mismatches to an XLSX file,
    with each set of file names in a separate sheet.

    :param in_file_list_not_in_metadata: List of file names in file lists, but not in metadata.
    :param in_metadata_not_in_file_list: List of file names in metadata, but not in file lists.
    :param output_file: Path to the output file.
    """
    output_path = Path("output").joinpath(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)  # Make `output/` dir, if none

    series_1 = pd.Series(in_file_list_not_in_metadata, name="filenames")
    series_2 = pd.Series(in_metadata_not_in_file_list, name="filenames")
    with pd.ExcelWriter(output_path) as writer:
        series_1.to_excel(writer, sheet_name="file_lists_not_metadata", index=False)
        series_2.to_excel(writer, sheet_name="metadata_not_file_lists", index=False)


def main():
    args = _get_arguments()

    file_lists = _get_file_paths(args.file_lists)
    metadata_assets = _get_metadata_assets(args.metadata_files)

    # Filter file_lists to only include strings that end with a file extension,
    # for comparison to file names in metadata_assets.
    file_names_in_file_lists = [
        Path(file_path).name
        for file_path in file_lists
        # Per FTVA, exclude JSON files
        if Path(file_path).suffix and Path(file_path).suffix.lower() != ".json"
    ]
    file_names_in_metadata = [
        # Replace empty file names with "NO FILE NAME"
        (
            asset["file_name"]
            if asset["file_name"] != ""
            else f"NO FILE NAME ({asset['uuid']})"
        )
        for asset in metadata_assets
    ]

    # Set A - in the file lists, but not the metadata, sorted alphabetically
    file_names_in_file_lists_not_in_metadata = sorted(
        set(file_names_in_file_lists) - set(file_names_in_metadata)
    )

    # Set B - in the metadata, but not the file lists, sorted alphabetically
    file_names_in_metadata_not_in_file_lists = sorted(
        set(file_names_in_metadata) - set(file_names_in_file_lists)
    )

    _write_report(
        file_names_in_file_lists_not_in_metadata,
        file_names_in_metadata_not_in_file_lists,
        args.output_file,
    )


if __name__ == "__main__":
    main()
