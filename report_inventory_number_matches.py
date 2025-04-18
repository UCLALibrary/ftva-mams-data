from collections import defaultdict
import csv
import json


def dump_counts(data: list[dict]) -> None:
    keys = defaultdict(set)
    for row in data:
        for key, val in row.items():
            if not isinstance(val, (dict, list)):
                keys[key].add(val)

    print()
    for key, val in keys.items():
        print(f"{key} has {len(val)} unique values")


if __name__ == "__main__":
    with open("FMExport_pretty.json", "r") as f:
        fm_data = json.load(f)
        fm_data = fm_data["Root"]["ROW"]
        fm_identifiers = [row["inventory_no"] for row in fm_data]
    print(f"FM data: {len(fm_identifiers)} rows")

    # Windows-derived CSV has leading BOM, so specify utf-8-sig, not utf-8
    with open("ftva_holdings_20250115.csv", encoding="utf-8-sig") as f:
        alma_data = csv.DictReader(f, dialect="excel")
        alma_data = [row for row in alma_data]
        alma_identifiers = [row["Permanent Call Number"] for row in alma_data]

    print(f"Alma data: {len(alma_identifiers)} rows")

    with open("google_sheet_batch_1.tsv", "r") as f:
        google_data = csv.DictReader(f, delimiter="\t")
        google_identifiers = [row["Inventory_no"] for row in google_data]

    print(f"Google batch 1 data: {len(google_identifiers)} rows")

    matches = set(fm_identifiers) & set(alma_identifiers)
    print(f"FM to Alma: {len(matches)} matches")

    matches = set(fm_identifiers) & set(alma_identifiers) & set(google_identifiers)
    print(f"FM to Alma and Google batch 1: {len(matches)} matches")

    alma_match_data = [
        row for row in alma_data if row["Permanent Call Number"] in matches
    ]
    print(f"Alma bib list data: {len(alma_match_data)} records")
    dump_counts(alma_match_data)

    with open("alma_match_data.json", "w") as f:
        json.dump(alma_match_data, f)
