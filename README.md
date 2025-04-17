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

### Retrieve FTVA holdings data from Alma

```python get_ftva_holdings_report.py [-h] --config_file CONFIG_FILE --output_file OUTPUT_FILE```

### Proof of concept for Filemaker API (find and display data)

```python filemaker_api_test.py [-h] --config_file CONFIG_FILE```

### Extract duplicate rows from FTVA spreadsheet

```python extract_duplicate_rows.py --data_file SPREADSHEET.xlsx [--tapes_tab_name TAB_NAME] [--output_duplicate_path OUTPUT_PATH.xlsx] [--remove_duplicates]```

This script extracts duplicate rows from the Tapes tab of the FTVA spreadsheet based on the "Legacy Path" column. Duplicate rows will be saved to the file specified by `--output_duplicate_path` (defaults to `duplicate_rows.xlsx` in the current directory).

If `--tapes_tab_name` is specified, the script will look for the tab with that name within the spreadsheet. Otherwise, it will look for a tab named "Tapes(row 4560-24712)".

If `--remove_duplicates` is specified, the script will remove the duplicate rows from the original spreadsheet and save it in place. Otherwise the original spreadsheet will not be modified.

### Extract inventory numbers from FTVA spreadsheet

```python extract_inventory_numbers.py --data_file SPREADSHEET.xlsx```

This script extracts inventory numbers from the values of the "Legacy Path" column in the Tapes tab of the FTVA spreadsheet. The script generates a copy of the input spreadsheet with a column appended named `Inventory Number [EXTRACTED]`, with matched inventory numbers. The copy is saved with the name `SPREADSHEET_with_inventory_numbers.xlsx` in the same directory as the input spreadsheet.