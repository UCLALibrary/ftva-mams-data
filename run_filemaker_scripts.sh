#!/bin/bash
set -e
cd /home/exlsupport/ftva-mams-data

DATE=$(date +%Y%m%d)
# Set the start and end dates for validation to be 14 days ago and today, respectively
START_DATE=$(date -d "-14 days" +%m/%d/%Y)
END_DATE=$(date +%m/%d/%Y)

BATCH_LOG="/tmp/filemaker_batch_update_${DATE}.log"
VALIDATION_LOG="/tmp/filemaker_validation_report_${DATE}.log"

LAYOUTS=("InventoryForLabeling_API" "NEW DIGITAL_API" "NEW DIGITAL STORAGE_API")
VALIDATION_CSVS=()

uv run filemaker_batch_update.py \
  --config_file prod_config_secrets.toml \
  -f production_type Language director release_broadcast_year record_date \
  > "$BATCH_LOG" 2>&1

for LAYOUT in "${LAYOUTS[@]}"; do
  SLUG=$(echo "$LAYOUT" | tr ' ' '_')
  OUTPUT_CSV="/tmp/filemaker_validation_report_${DATE}_${SLUG}.csv"
  uv run filemaker_validation_report.py \
    --config_file prod_config_secrets.toml \
    --start_date "$START_DATE" \
    --end_date "$END_DATE" \
    --layout "$LAYOUT" \
    --output_csv "$OUTPUT_CSV" \
    >> "$VALIDATION_LOG" 2>&1
  VALIDATION_CSVS+=("$OUTPUT_CSV")
done


# Compress any validation CSV over ~1MB so the combined email stays under
# the message_size_limit (10240000 bytes on p-u-exlsupport01)
COMPRESS_THRESHOLD=1000000

FINAL_CSVS=()
for CSV in "${VALIDATION_CSVS[@]}"; do
  if [ ! -f "$CSV" ]; then
    continue  # no violations for this layout; no CSV was written
  fi
  SIZE=$(stat -c%s "$CSV")
  if [ "$SIZE" -gt "$COMPRESS_THRESHOLD" ]; then
    gzip -f "$CSV"
    FINAL_CSVS+=("${CSV}.gz")
  else
    FINAL_CSVS+=("$CSV")
  fi
done

ATTACHMENTS=(-a "$VALIDATION_LOG")
for FILE in "${FINAL_CSVS[@]}"; do
  ATTACHMENTS+=(-a "$FILE")
done

mail -s "FTVA FileMaker batch/validation report $(date +%F)" \
     "${ATTACHMENTS[@]}" \
     -c akohler@library.ucla.edu \
     shogsett@cinema.ucla.edu,amanda.mack@cinema.ucla.edu \
     <<< "See attached logs and validation reports (one per layout) for FileMaker batch update and validation, run on $(date +%F)."
