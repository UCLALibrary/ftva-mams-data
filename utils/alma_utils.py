import logging

from ftva_etl import AlmaSRUClient
from ftva_etl.metadata.utils import filter_by_inventory_number_and_library

# For type hints
from pymarc import Record as Pymarc_Record


def get_alma_bib_record_with_possible_suffix(
    inv_no_stem: str,
    alma_sru_client: AlmaSRUClient,
    logger: logging.Logger | None = None,
) -> Pymarc_Record | None:
    """Get the first matching Alma bib record for the provided inventory number,
    retrying with suffixes "T", "M", and "R" if no record is found without suffix.

    :param inv_no_stem: The base inventory number to search for.
    :param alma_sru_client: The AlmaSRUClient instance to use to get the bib record.
    :param logger: Optional logger for log messages.
    :return: The first Alma record matching the inventory number,
        or None if no record is found.
    """
    _logger = logger or logging.getLogger(__name__)
    # Try no suffix first, then "T", "M", and "R".
    # NOTE: The additional suffixes are a shim
    # to deal with inconsistent inventory numbers across systems.
    suffixes = ["", "T", "M", "R"]
    inv_nos_to_check = [inv_no_stem + suffix for suffix in suffixes]
    bib_record = None
    for inv_no in inv_nos_to_check:
        search_results = alma_sru_client.search_by_call_number(inv_no)
        filtered_bib_records: list[Pymarc_Record] = (
            filter_by_inventory_number_and_library(search_results, inv_no)
        )
        if filtered_bib_records:
            # Take the first record that matches the inventory number and is from FTVA
            bib_record = filtered_bib_records[0]
            if inv_no != inv_no_stem:
                _logger.info(
                    f"Inventory number '{inv_no_stem}' from DD "
                    f"matched to '{inv_no}' in Alma."
                )
            break
    return bib_record
