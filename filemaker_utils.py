import logging
import tomllib
from datetime import datetime
from pathlib import Path

from ftva_etl import FilemakerClient
from fmrest.exceptions import FileMakerError
from fmrest.record import Record


def configure_logging(logger: logging.Logger, suffix: str = "") -> None:
    """Configure file + console handlers on *logger*.

    :param logger: The module-level logger to configure.
    :param suffix: Optional suffix appended to the log file name
                   (e.g. ``"_DRY_RUN"``).
    """
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{logger.name}_{timestamp}{suffix}.log"

    file_formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    console_formatter = logging.Formatter("%(message)s")

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def get_config(config_file_name: str) -> dict:
    """Load and return configuration from a TOML file.

    :param config_file_name: Path to the TOML configuration file.
    :return: Configuration dict.
    """
    with open(config_file_name, "rb") as f:
        return tomllib.load(f)


def initialize_client(
    config: dict,
    logger: logging.Logger,
    layout: str | None = None,
) -> FilemakerClient:
    """Initialize and return a configured Filemaker client.

    :param config: Program configuration dict loaded from TOML.
    :param logger: Logger for status/error messages.
    :param layout: FM layout name to connect to.  If provided, overrides the
        ``layout`` key in the config file.  Use this when a script needs to
        connect to multiple layouts in one run.
    :return: An initialized ``FilemakerClient`` instance.
    :raises FileMakerError: If the connection to Filemaker fails.
    """
    fm_config = config.get("filemaker", {})
    # Build kwargs from config, only passing keys that are present,
    # so FilemakerClient's own defaults apply for anything not in the file.
    kwargs: dict = {
        "user": fm_config.get("user", ""),
        "password": fm_config.get("password", ""),
    }
    for key in ("url", "database", "layout", "api_version", "timeout"):
        if key in fm_config:
            kwargs[key] = fm_config[key]
    # Explicit layout argument takes precedence over config file.
    if layout is not None:
        kwargs["layout"] = layout
    try:
        client = FilemakerClient(**kwargs)
        logger.info(f"Connected to Filemaker layout {kwargs.get('layout')!r}.")
        return client
    except FileMakerError as e:
        logger.error(f"Failed to connect to Filemaker: {e}")
        raise


# --------------------
# Record retrieval
# --------------------


def get_all_records(
    fm_client: FilemakerClient,
    page_size: int,
    offset: int = 1,
    logger: logging.Logger | None = None,
) -> list[Record]:
    """Retrieve every record in the Filemaker database, paginating automatically.

    :param fm_client: A configured FilemakerClient instance.
    :param page_size: Number of records to retrieve at a time.
    :param offset: Position (NOT record_id) to start at. Default: 1.
    :param logger: Optional logger for progress messages.
    :return: List of all fmrest ``Record`` objects.
    """
    _log = logger or logging.getLogger(__name__)
    _log.info(f"Retrieving all records in pages of {page_size}...")

    all_records = []
    current_offset = offset

    while True:
        batch = fm_client.get_records(offset=current_offset, limit=page_size)
        if not batch:
            _log.info("Pagination complete. All records retrieved.")
            break
        _log.info(
            f"Retrieved records {current_offset} to "
            f"{current_offset + len(batch) - 1}..."
        )
        all_records.extend(batch)
        if len(batch) < page_size:
            _log.info("Pagination complete. All records retrieved.")
            break
        current_offset += page_size

    return all_records
