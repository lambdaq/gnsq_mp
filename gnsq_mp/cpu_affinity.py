# -*- coding: utf-8 -*-
"""CPU affinity helpers built on :mod:`os`.

Only available on platforms that provide ``os.sched_setaffinity`` (Linux).
Everywhere else the helpers silently do nothing.
"""

import os


def is_supported():
    return hasattr(os, 'sched_setaffinity')


def available_cpus():
    """CPUs the current process is allowed to run on (sorted list)."""
    if not is_supported():
        return []
    return sorted(os.sched_getaffinity(0))


class ProcessAffinity(object):
    """Get/set the CPU affinity of a process.

    Usage::

        ProcessAffinity(pid).affinity = 3          # a single cpu
        ProcessAffinity(pid).affinity = (1, 3)     # several cpus
    """

    def __init__(self, pid=0):
        self.pid = pid

    @property
    def affinity(self):
        if not is_supported():
            return None
        try:
            return set(os.sched_getaffinity(self.pid))
        except OSError:
            return None

    @affinity.setter
    def affinity(self, values):
        if not is_supported():
            return
        if isinstance(values, int):
            values = (values,)
        try:
            os.sched_setaffinity(self.pid, set(values))
        except (OSError, ValueError):
            # process already gone, or cpu not allowed
            pass
