# -*- coding: utf-8 -*-
"""Controller: polls nsqlookupd and keeps one worker process per nsqd."""

import os
import random
import signal
import subprocess
import sys
import time
from collections import OrderedDict

from gnsq import LookupdClient

from ._internal import configure_logging, logger
from .cpu_affinity import ProcessAffinity, available_cpus


class NsqMPController(object):
    """Spawn and supervise one worker process for every nsqd of a topic.

    Subclass it and set :attr:`lookupd_http_addresses` and :attr:`worker`::

        class MyController(NsqMPController):
            lookupd_http_addresses = ['http://127.0.0.1:4161']
            worker = 'worker.py'

        MyController.run(topic='blah', channel_name='mychannel')

    Every worker is started as::

        <python> <worker> <topic> <nsqd_tcp_addr> <channel_name> [extra_args ...]
    """

    #: nsqlookupd http addresses, e.g. ``['http://10.0.0.1:4161']``.
    lookupd_http_addresses = []
    #: Path of the worker script. Relative paths are resolved against the
    #: directory of the module defining the controller class.
    worker = None
    #: Python interpreter used to run the worker.
    python_executable = sys.executable
    #: Seconds between two checks of the worker processes.
    poll_interval = 5
    #: Seconds between two nsqlookupd queries.
    lookup_interval = 30
    #: Minimum seconds between two (re)starts of the worker of the same nsqd.
    restart_delay = 5
    #: Seconds to wait for workers to exit gracefully before killing them.
    stop_timeout = 15
    #: Pin every worker to one cpu core (Linux only).
    pin_cpu = True

    def __init__(self, topic, channel_name='gnsq_mp', max_procs=0,
                 extra_args=(), lookupd_http_addresses=None, worker=None):
        """
        :param topic: nsq topic to consume.
        :param channel_name: nsq channel to consume.
        :param max_procs: max number of worker processes, 0 means no limit.
        :param extra_args: extra command line arguments for every worker.
        :param lookupd_http_addresses: overrides the class attribute.
        :param worker: overrides the class attribute.
        """
        cls = self.__class__
        self.topic = topic
        self.channel_name = channel_name
        self.max_procs = max_procs
        self.extra_args = [str(x) for x in extra_args]

        addrs = lookupd_http_addresses or cls.lookupd_http_addresses
        if not addrs:
            raise ValueError('Empty lookupd_http_addresses')
        worker = worker or cls.worker
        if not worker:
            raise NotImplementedError('need define worker script path')
        self.worker_abspath = self._resolve_worker(worker)
        if not os.path.isfile(self.worker_abspath):
            raise FileNotFoundError(self.worker_abspath)

        self.lookupds = [LookupdClient.from_url(x) for x in addrs]
        self._lookupd_idx = random.randrange(len(self.lookupds))

        self._procs = OrderedDict()   # nsqd addr -> Popen
        self._cpus = {}               # nsqd addr -> pinned cpu
        self._last_start = {}         # nsqd addr -> monotonic time
        self._stopping = []           # [(Popen, kill deadline)]
        self._targets = []            # nsqd addrs we want a worker for
        self._stop_requested = False

        logger.info('[controller] topic=%s channel=%s worker=%s',
                    topic, channel_name, self.worker_abspath)

    # -- discovery -------------------------------------------------------

    def _resolve_worker(self, worker):
        module = sys.modules.get(self.__class__.__module__)
        base = os.path.dirname(os.path.abspath(
            getattr(module, '__file__', None) or os.path.join(os.getcwd(), '_')))
        return os.path.abspath(os.path.join(base, worker))

    def get_producer_addrs(self):
        """Query nsqlookupd and return the ``host:port`` of every nsqd.

        Every lookupd is tried (round robin), the first answer wins.
        """
        error = None
        for _ in range(len(self.lookupds)):
            client = self.lookupds[self._lookupd_idx % len(self.lookupds)]
            self._lookupd_idx += 1
            try:
                producers = client.lookup(self.topic)['producers']
            except Exception as e:  # network error, topic not found, ...
                logger.warning('[controller] lookupd %s failed: %r',
                               client.address, e)
                error = e
                continue
            addrs = []
            for p in producers:
                host = p.get('broadcast_address') or p['address']
                if ':' in host:  # ipv6
                    host = '[%s]' % host
                addrs.append('%s:%s' % (host, p['tcp_port']))
            random.shuffle(addrs)
            return addrs
        raise error

    def select_targets(self, producers):
        """Apply ``max_procs``, keeping already running workers first."""
        if self.max_procs <= 0 or len(producers) <= self.max_procs:
            return list(producers)
        keep = [x for x in self._procs if x in producers]
        keep = keep[:self.max_procs]
        others = [x for x in producers if x not in keep]
        return keep + others[:self.max_procs - len(keep)]

    # -- process management ---------------------------------------------

    def _pick_cpu(self):
        cpus = available_cpus()
        if not cpus:
            return None
        used = list(self._cpus.values())
        return min(cpus, key=lambda c: (used.count(c), c))

    def _spawn(self, addr):
        proc = subprocess.Popen(
            [self.python_executable, self.worker_abspath,
             self.topic, addr, self.channel_name] + self.extra_args)
        self._procs[addr] = proc
        self._last_start[addr] = time.monotonic()
        if self.pin_cpu:
            cpu = self._pick_cpu()
            if cpu is not None:
                self._cpus[addr] = cpu
                ProcessAffinity(proc.pid).affinity = cpu
        logger.info('[controller] spawn pid=%s nsqd=%s procs=%d',
                    proc.pid, addr, len(self._procs))

    def _terminate(self, addr):
        proc = self._procs.pop(addr)
        self._cpus.pop(addr, None)
        self._last_start.pop(addr, None)
        if proc.poll() is None:
            proc.terminate()
            self._stopping.append(
                (proc, time.monotonic() + self.stop_timeout))
        logger.info('[controller] terminate pid=%s nsqd=%s', proc.pid, addr)

    def _reap_stopping(self):
        alive = []
        for proc, deadline in self._stopping:
            if proc.poll() is not None:
                continue
            if time.monotonic() > deadline:
                logger.warning('[controller] kill pid=%s', proc.pid)
                proc.kill()
                proc.wait()
                continue
            alive.append((proc, deadline))
        self._stopping = alive

    def check_worker(self):
        """Reconcile running workers with the wanted nsqd list."""
        for addr in list(self._procs):
            if addr not in self._targets:
                self._terminate(addr)
        for addr in self._targets:
            if self._stop_requested:
                return
            proc = self._procs.get(addr)
            if proc is not None:
                rc = proc.poll()
                if rc is None:
                    continue
                logger.warning('[controller] worker exited pid=%s rc=%s '
                               'nsqd=%s', proc.pid, rc, addr)
                self._procs.pop(addr)
                self._cpus.pop(addr, None)
            last = self._last_start.get(addr)
            if last is not None and time.monotonic() - last < self.restart_delay:
                continue  # avoid crash loops
            self._spawn(addr)
        self._reap_stopping()

    def refresh_targets(self):
        """Query lookupd; on failure keep the current targets."""
        try:
            producers = self.get_producer_addrs()
        except Exception:
            return False
        self._targets = self.select_targets(producers)
        return True

    # -- lifecycle -------------------------------------------------------

    def request_stop(self, signum=None, frame=None):
        self._stop_requested = True

    def _sleep(self, seconds):
        end = time.monotonic() + seconds
        while not self._stop_requested:
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.5, left))

    def kill_all(self):
        """Stop every worker: SIGTERM first, SIGKILL after ``stop_timeout``."""
        procs = list(self._procs.values()) + [p for p, _ in self._stopping]
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.monotonic() + self.stop_timeout
        for proc in procs:
            try:
                proc.wait(max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                logger.warning('[controller] kill pid=%s', proc.pid)
                proc.kill()
                proc.wait()
            logger.info('[controller] stopped pid=%s rc=%s',
                        proc.pid, proc.returncode)
        self._procs.clear()
        self._stopping = []
        self._cpus.clear()

    def run_forever(self):
        next_lookup = 0
        while not self._stop_requested:
            now = time.monotonic()
            if now >= next_lookup:
                ok = self.refresh_targets()
                next_lookup = now + (
                    self.lookup_interval if ok else self.poll_interval)
            self.check_worker()
            self._sleep(self.poll_interval)
        logger.info('[controller] stopping...')
        self.kill_all()
        logger.info('[controller] all subprocess stopped.')

    @classmethod
    def run(cls, *args, **kwargs):
        configure_logging()
        inst = cls(*args, **kwargs)
        signal.signal(signal.SIGINT, inst.request_stop)
        signal.signal(signal.SIGTERM, inst.request_stop)
        inst.run_forever()
        return inst
