# ftva-mams-data
Tools for FTVA  / MAMS data cleanup and preparation

# Developer Information

## Build (first time) / rebuild (as needed)

`docker compose build`

This builds a Docker image, `ftva-mams-data-ftva_data:latest`, which can be used for developing, testing, and running code.

## Dev container

This project comes with a basic dev container definition, in `.devcontainer/devcontainer.json`. It's known to work with VS Code,
and may work with other IDEs like PyCharm.  For VS Code, it also installs the Python, Black (formatter), and Flake8 (linter)
extensions.

The project's directory is available within the container at `/home/ftva_data/project`.

### Rebuilding the dev container

VS Code builds its own container from the base image. This container may not always get rebuilt when the base image is rebuilt
(e.g., if packages are changed via `requirements.txt`).

If needed, rebuild the dev container by:
1. Close VS Code and wait several seconds for the dev container to shut down (check via `docker ps`).
2. Delete the dev container.
   1. `docker images | grep vsc-ftva-mams-data` # vsc-ftva-mams-data-LONG_HEX_STRING-uid
   2. `docker image rm -f vsc-ftva-mams-data-LONG_HEX_STRING-uid`
3. Start VS Code as usual.

## Running code

Running code from a VS Code terminal within the dev container should just work, e.g.: `python some_script.py` (whatever the specific program is).

Otherwise, run a program via docker compose.  From the project directory:

```
# Open a shell in the container
$ docker compose run ftva_data bash

# Open a Python shell in the container
$ docker compose run ftva_data python
```

### Secrets

Some data sources require API keys or other secrets. Get a copy of the relevant configuration file from a teammate and put it in the top level directory of the project.

The config file currently looks like this (with secret values redacted):
```
[alma_config]
alma_api_key = "SECRET"
analytics_api_key = "SECRET"
ftva_holdings_report =  "/shared/University of California Los Angeles (UCLA) 01UCS_LAL/Cataloging/Reports/API/FTVA Holdings"

[filemaker]
api_version="vLatest"
database="Inventory for Labeling"
layout="InventoryForLabeling_ReadOnly_API"
password="YOUR_PASSWORD"
url = "https://adam.cinema.ucla.edu"
user="YOUR_NAME"
```

## Scripts

### Retrieve all Filemaker records

```python filemaker_get_all_records.py --config_file CONFIG_FILE```

This can take 20-30 minutes to run. It creates a large JSON file, about 2.5 GB, with all records in the
FTVA processing database (aka the Labeling database) - about 607,000 records as of 4/2025.
Every available field of every record is included. The program writes all records to `filemaker_data_{DATE}_{TIME}.json`.

### Retrieve FTVA holdings data from Alma

```python get_ftva_holdings_report.py --config_file CONFIG_FILE --output_file OUTPUT_FILE```

This script retrieves a few fields from Alma bib and holdings records associated with FTVA: bib and holdings ids, call number, and location.
It writes to the provided `OUTPUT_FILE`, in CSV format - about 368,000 records as of 4/2025.

### Proof of concept for Filemaker API (find and display data)

```python filemaker_api_test.py --config_file CONFIG_FILE```

### Extract duplicate rows from FTVA spreadsheet

```python extract_duplicate_rows.py --data_file SPREADSHEET.xlsx [--tapes_tab_name TAB_NAME] [--output_duplicate_path OUTPUT_PATH.xlsx] [--remove_duplicates]```

This script extracts duplicate rows from the Tapes tab of the FTVA spreadsheet based on the "Legacy Path" column. Duplicate rows will be saved to the file specified by `--output_duplicate_path` (defaults to `duplicate_rows.xlsx` in the current directory).

If `--tapes_tab_name` is specified, the script will look for the tab with that name within the spreadsheet. Otherwise, it will look for a tab named "Tapes(row 4560-24712)".

If `--remove_duplicates` is specified, the script will remove the duplicate rows from the original spreadsheet and save it in place. Otherwise the original spreadsheet will not be modified.

### Extract inventory numbers from FTVA spreadsheet

```python extract_inventory_numbers.py --data_file SPREADSHEET.xlsx```

This script extracts inventory numbers from the values of the "Legacy Path" column in the Tapes tab of the FTVA spreadsheet. The script generates a copy of the input spreadsheet with a column appended named `Inventory Number [EXTRACTED]`, with matched inventory numbers. The copy is saved with the name `SPREADSHEET_with_inventory_numbers.xlsx` in the same directory as the input spreadsheet.

### Report FTVA inventory number matches across multiple data sources

```
python report_inventory_number_matches.py \
     --alma_file FTVA_HOLDINGS.csv \
     --filemaker_data_file FILEMAKER_DATA.json \
     --google_file GOOGLE_SHEET.xlsx
```

This script compares FTVA inventory numbers from 3 sources:
* Alma (obtained by running `get_ftva_holdings_report.py`)
* Filemaker (obtained by running `filemaker_get_all_records.py`)
* Google sheets (obtained by downloading the relevant file in Excel format, all sheets.)
  * Only the "Tapes(row 4560-24712)" sheet is used by this script.

The script loads data from all 3 files and compares inventory numbers from all sources in a variety of ways:
* Inventory numbers with perfect matches (1-1-1) across all 3 sources
* Inventory numbers with perfect matches (1-1) across each pair of sources (Alma/Filemaker, Alma/Google, Filemaker/Google)
* Inventory numbers occurring in only one source
  * Alma: "Other Identifiers" column lists the Alma holdings id(s) for each inventory number
  * Filemaker: "Other Identifiers" column lists the FM record id(s) for each inventory number
  * Google: "Other Identifiers" column lists the sheet's row number(s) for each inventory number

All output is written to an Excel file, `inventory_number_matches.xlsx`. If the file already exists, worksheets
within it are replaced as each part of the script runs.  The script takes about 2 minutes to run.

Various counts are also written to `STDOUT`.  Using the latest available data as of 4/22/2025:
```
Counts for Alma inventory numbers: 368247 total, 256337 distinct, 228785 singletons, 0 empty
Counts for Filemaker inventory numbers: 606136 total, 553318 distinct, 530993 singletons, 0 empty
Counts for Google inventory numbers: 20362 total, 4462 distinct, 1476 singletons, 3983 empty
Perfect matches for all 3 sources: 608
Perfect matches for Alma and Filemaker: 189956
Perfect matches for Alma and Google: 627
Perfect matches for Filemaker and Google: 1381
Only in Alma: 47804
Only in Filemaker: 342763
Only in Google: 57
```
