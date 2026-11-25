# -*- coding: utf-8 -*-
"""Multi-process NSQ consumers on top of gnsq.

``NsqProcessWorker`` monkey patches the standard library with gevent when its
module is imported, so it is imported lazily: a controller process that only
imports ``NsqMPController`` stays unpatched.
"""

__version__ = '0.3.0'

__all__ = ['NsqMPController', 'NsqProcessWorker']


def __getattr__(name):
    if name == 'NsqMPController':
        from .master import NsqMPController
        return NsqMPController
    if name == 'NsqProcessWorker':
        from .worker import NsqProcessWorker
        return NsqProcessWorker
    raise AttributeError('module %r has no attribute %r' % (__name__, name))
