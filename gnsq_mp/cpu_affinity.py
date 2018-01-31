# coding: utf-8

from ctypes import cdll, Structure, c_int32, sizeof, byref


class cpu_set_t(Structure):  # NOQA
    _fields_ = [('bits', c_int32 * 8)]

libc = cdll.LoadLibrary('libc.so.6')


class ProcessAffinity(object):

    def __init__(self, pid=0):
        self.pid = pid

    @property
    def affinity(self):
        cs = cpu_set_t()
        ec = libc.sched_getaffinity(0, sizeof(cs), byref(cs))
        if ec == 0:
            return cs.bits[0]

    @affinity.setter
    def affinity(self, values):
        """use like proc_aff.affinity = 1,3"""
        cs = cpu_set_t()
        if not isinstance(values, tuple):
            values = (values,)
        for v in values:
            i, b = divmod(v, 1 << 32)
            cs.bits[i] |= (1 << b)
        ec = libc.sched_setaffinity(0, sizeof(cs), byref(cs))
        return ec
