# -*- coding: utf-8 -*-
"""Internal helpers: the package logger."""

import logging

logger = logging.getLogger('gnsq_mp')
# Libraries must not configure logging on their own; stay silent unless the
# application (or ``configure_logging`` below) installs a handler.
logger.addHandler(logging.NullHandler())


def configure_logging(level=logging.INFO):
    """Install a basic stderr handler if the application has not set up any.

    Called by the ``run()`` entry points of the controller and the worker,
    which are meant to be used as standalone processes.
    """
    if logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s %(name)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
