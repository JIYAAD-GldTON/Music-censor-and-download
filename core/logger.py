"""
Centralized logging configuration for Cuss-Censor.
Provides uniform formatting and verbosity controls across all modules.
"""

import logging
import sys
import os

LOG_LEVEL = os.getenv("CUSS_CENSOR_LOG_LEVEL", "INFO").upper()

_logger_initialized = False


def setup_logger(level: str = LOG_LEVEL) -> logging.Logger:
    """Set up and return the root logger for cuss_censor."""
    global _logger_initialized
    logger = logging.getLogger("cuss_censor")

    if not _logger_initialized:
        numeric_level = getattr(logging, level, logging.INFO)
        logger.setLevel(numeric_level)

        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        _logger_initialized = True

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger with the given module name."""
    if not _logger_initialized:
        setup_logger()
    return logging.getLogger(f"cuss_censor.{name}")
