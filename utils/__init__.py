"""
Shared utility modules for ftva-mams-data scripts.
This package does not re-export functions from submodules. Callers must write imports like:

from utils.filemaker_utils import configure_logging

instead of

from utils import configure_logging

This is done to avoid loading spaCy in contexts where we don't need it.
Since __init__.py is executed on import, if we re-exported the spacy_utils functions here,
spaCy would be loaded whenever any utils function is imported, including those in other modules.

Modules
-------
filemaker_utils
    Client initialization, configuration loading, logging setup,
    and record retrieval helpers for Filemaker.
spacy_utils
    NLP helpers using spaCy.
"""
