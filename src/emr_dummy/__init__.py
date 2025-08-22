import logging
import os
import sys

from rdsa_utils.logging import init_logger_advanced

# Determine log level from environment or default to INFO
LOG_LEVEL_STR = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

# Initialise the logger once for the entire package
init_logger_advanced(
    log_level=LOG_LEVEL,
    handlers=[logging.StreamHandler(sys.stdout)],
    log_format="%(asctime)s (%(levelname)s) [%(name)s] %(message)s",
    date_format="%Y-%m-%d %H:%M:%S",
)
