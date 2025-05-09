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

### Running tests

Several scripts have tests.  To run tests:
```
$ docker compose run ftva_data python -m unittest
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

Examples below assume you're running them in an existing `bash` shell within the container.  To run from outside, launching
a container, add `docker compose run ftva_data ` to the beginning of the command (e.g., 
`docker compose run ftva_data python filemaker_get_all_records.py --config_file CONFIG_FILE` ).

### Retrieve all Filemaker records

```python filemaker_get_all_records.py --config_file CONFIG_FILE```

This can take 20-30 minutes to run. It creates a large JSON file, about 2.5 GB, with all records in the
FTVA processing database (aka the Labeling database) - about 607,000 records as of 4/2025.
Every available field of every record is included. The program writes all records to `filemaker_data_{DATE}_{TIME}.json`.

### Retrieve FTVA holdings data from Alma

```python get_ftva_holdings_report.py --config_file CONFIG_FILE --output_file OUTPUT_FILE```

This script retrieves a few fields from Alma bib and holdings records associated with FTVA: bib and holdings ids, call number, and location.
It writes to the provided `OUTPUT_FILE`, in CSV format - about 368,000 records as of 4/2025. It takes about 6 minutes to run.

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
     --google_file GOOGLE_SHEET.xlsx \
     --output_file REPORT_FILE.xlsx
```

This script compares FTVA inventory numbers from 3 sources:
* Google sheets (obtained by downloading the relevant file in Excel format, all sheets.)
  * Only the "Tapes(row 4560-24712)" sheet is used by this script.
* Alma (obtained by running `get_ftva_holdings_report.py`)
* Filemaker (obtained by running `filemaker_get_all_records.py`)

The script loads data from all 3 files and compares inventory numbers in a variety of ways:
* Google single values matching multiple records in Alma, Filemaker, or both
* Google compound values (e.g., "M123|DVD431") where each individual inventory number matches only one Alma or Filemaker record
* Google compound values where at least one individual inventory number matches multiple Alma and/or Filemaker records

All output is written to an Excel file. If the file already exists, worksheets
within it are replaced as each part of the script runs.  The script takes about 2 minutes to run.

Various counts are also written to `STDOUT`.  Using the latest available data as of 5/8/2025:
```
Counts for Alma inventory numbers: 368268 total, 256375 distinct, 27536 repeats, 228839 singletons, 0 empty.
Counts for Filemaker inventory numbers: 606225 total, 553416 distinct, 22320 repeats, 531096 singletons, 1 empty.
Counts for Google Sheet inventory numbers: 19641 total, 4596 distinct, 4356 single values, 240 multiple values, 3983 empty.

len(multiple_fm_no_alma)=92
len(multiple_alma_no_fm)=12
len(multiple_fm_one_alma)=9
len(multiple_alma_one_fm)=421
len(multiple_fm_multiple_alma)=179
len(no_fm_no_alma)=44
len(leftovers)=3599

Multi-match counts before de-duping
len(each_to_one_fm_or_alma)=200
len(at_least_one_to_mult_fm_or_alma)=40
len(leftovers)=248

Multi-match counts after de-duping
len(each_to_one_fm_or_alma)=167
len(at_least_one_to_mult_fm_or_alma)=28
len(leftovers)=224
```
