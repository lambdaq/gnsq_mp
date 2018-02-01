#!/home/sail/miniconda2/bin/python
# coding: utf-8

import sys, os
import random
from itertools import cycle
from collections import OrderedDict

from gnsq import Lookupd
from gevent import subprocess, sleep

from cpu_affinity import ProcessAffinity


def safe_str(s):
    if isinstance(s, unicode):
        return s.encode('utf-8')
    return s


class NsqMPController(object):

    lookupd_http_addresses = []
    worker = None  # Need to specify this

    def __init__(self, topic, channel_name='gnsq_mp'):
        self.topic = topic
        self.channel_name = channel_name
        self._procs = OrderedDict()
        self.poll_count = 0
        if not self.__class__.lookupd_http_addresses:
            raise ValueError('Empty lookupd_http_addresses')
        if not self.__class__.worker:
            raise NotImplementedError('need define worker script path')
        self.worker_abspath = os.path.abspath(os.path.join(
            sys.modules[self.__class__.__module__].__file__,
            '..', self.__class__.worker))
        print>>sys.stderr, ' [nsq_mp] worker: %s' % self.worker_abspath
        self.lookupds = cycle(Lookupd(x) for x in self.__class__.lookupd_http_addresses)

    @property
    def rand_lookup(self):
        # random.shuffle returns None so fuck it.
        return next(self.lookupds)

    def get_producer_addrs(self):
        return [
            '%s:%s' % (
                x.get('broadcast_address') or x['address'],
                x['tcp_port']  # also: producer['http_port']
            ) for x in self.rand_lookup.lookup(self.topic)['producers']]

    def check_worker(self):
        if self.poll_count % 10 == 0:
            # check for producers every 30 seconds
            producers = self.get_producer_addrs()
        else:
            # check for process every 3 seconds
            producers = self._procs.keys()
        for i, nsqd_tcp_addr in enumerate(producers):
            proc = self._procs.get(nsqd_tcp_addr)
            # if nslookupd found a new producer
            # or the spawned subprocess exited, .poll() has a returnvalue
            if proc is None or proc.poll() is not None:
                proc = subprocess.Popen([
                    sys.executable, self.worker_abspath,
                    self.topic, nsqd_tcp_addr, self.channel_name])
                ProcessAffinity(proc.pid).affinity = i
                print>>sys.stderr, ' [spawn] pid=%s, nsqd=%s' % (proc.pid, nsqd_tcp_addr)
                self._procs[nsqd_tcp_addr] = proc
        self.poll_count += 1

    @classmethod
    def run(cls, *args, **kwargs):
        inst = cls(*args, **kwargs)
        try:
            while 1:
                inst.check_worker()
                sleep(3)
        except KeyboardInterrupt:
            for k, p in inst._procs.iteritems():
                p.send_signal(2)
                p.wait()
                print>>sys.stderr, ' [kill] %s pid=%s, rc=%d' % (k, p.pid, p.returncode)
            print>>sys.stderr, ' [exit] all subprocess stopped.'
            exit(0)
        return inst


if '__main__' == __name__:
    NsqMPController.run("test_topic", "test_channel")
