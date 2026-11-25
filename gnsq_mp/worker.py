# -*- coding: utf-8 -*-
"""Worker: consumes one topic/channel from a single nsqd.

NOTE: importing this module monkey patches the standard library with gevent
(``gnsq`` needs it). Import it from the worker script only, and import it
before other network libraries.
"""

from gevent import monkey; monkey.patch_all()  # noqa: E702

import argparse
import os
import signal
import sys

import gevent
from gnsq import Consumer

from ._internal import configure_logging, logger


class NsqProcessWorker(object):
    """Base class of a worker script. Override :meth:`handle_message`::

        class MyWorker(NsqProcessWorker):
            def handle_message(self, consumer, message):
                print(message.body)

        if __name__ == '__main__':
            MyWorker.run()

    The script is started by :class:`~gnsq_mp.NsqMPController` with the
    arguments ``topic nsqd_tcp_addr channel [extra_args ...]`` and can also be
    run by hand with the same arguments.
    """

    #: ``max_in_flight`` of the consumer.
    max_in_flight = 200
    #: More keyword arguments for :class:`gnsq.Consumer`.
    consumer_options = {}
    #: Seconds to wait for in flight messages on shutdown.
    shutdown_timeout = 8
    #: Seconds between two checks whether the controller is still alive.
    parent_check_interval = 2

    def __init__(self, topic, nsqd_addr, channel, extra_args=()):
        self.topic = topic
        self.nsqd_addr = nsqd_addr
        self.channel = channel
        self.extra_args = list(extra_args)
        self._ppid = os.getppid()
        self._closing = False
        options = dict(max_in_flight=self.max_in_flight)
        options.update(self.consumer_options)
        self.consumer = Consumer(
            topic, channel,
            nsqd_tcp_addresses=[nsqd_addr],
            message_handler=self.handle_message,
            **options)

    #: kept for backward compatibility
    reader = property(lambda self: self.consumer)

    def handle_message(self, consumer, message):
        """Called for every message. The message is finished automatically
        if this returns, and requeued if it raises."""
        raise NotImplementedError

    # -- lifecycle -------------------------------------------------------

    def _watch_parent(self):
        """Exit when the controller died (we were re-parented)."""
        while not self._closing:
            if os.getppid() != self._ppid:
                logger.warning('[worker] controller is gone, exit. pid=%s',
                               os.getpid())
                self.shutdown()
                return
            gevent.sleep(self.parent_check_interval)

    def _force_exit(self):
        logger.error('[worker] shutdown timed out, force exit. pid=%s',
                     os.getpid())
        os._exit(1)

    def shutdown(self, *args):
        if self._closing:
            return
        self._closing = True
        logger.info('[worker] closing. pid=%s nsqd=%s', os.getpid(),
                    self.nsqd_addr)
        gevent.spawn_later(self.shutdown_timeout, self._force_exit)
        self.consumer.close()

    def start(self, block=True):
        for signum in (signal.SIGINT, signal.SIGTERM):
            gevent.signal_handler(signum, self.shutdown)
        gevent.spawn(self._watch_parent)
        logger.info('[worker] start. pid=%s topic=%s channel=%s nsqd=%s',
                    os.getpid(), self.topic, self.channel, self.nsqd_addr)
        self.consumer.start(block=block)

    @classmethod
    def parse_args(cls, argv=None):
        parser = argparse.ArgumentParser(
            description='gnsq_mp worker: consume from a single nsqd.')
        parser.add_argument('topic')
        parser.add_argument('nsqd_addr', help='nsqd tcp address, host:port')
        parser.add_argument('channel')
        parser.add_argument('extra_args', nargs='*')
        return parser.parse_args(argv)

    @classmethod
    def run(cls, block=True, argv=None):
        """Entry point of the worker script."""
        configure_logging()
        args = cls.parse_args(argv)
        inst = cls(args.topic, args.nsqd_addr, args.channel, args.extra_args)
        inst.start(block=block)
        return inst
