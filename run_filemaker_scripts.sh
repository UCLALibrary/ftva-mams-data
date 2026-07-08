#!/bin/bash
set -e
cd /home/exlsupport/ftva-mams-data

DATE=$(date +%Y%m%d)
BATCH_LOG="/tmp/filemaker_batch_update_${DATE}.log"
VALIDATION_LOG="/tmp/filemaker_validation_report_${DATE}.log"

uv run filemaker_batch_update.py --config_file prod_config_secrets.toml > "$BATCH_LOG" 2>&1
uv run filemaker_validation_report.py --config_file prod_config_secrets.toml > "$VALIDATION_LOG" 2>&1

mail -s "FTVA FileMaker batch/validation report $(date +%F)" \
     -a "$BATCH_LOG" \
     -a "$VALIDATION_LOG" \
     -c akohler@library.ucla.edu \
     shogsett@cinema.ucla.edu,amanda.mack@cinema.ucla.edu \
     <<< "See attached logs for FileMaker batch update script and validation report, run on $(date +%F)."