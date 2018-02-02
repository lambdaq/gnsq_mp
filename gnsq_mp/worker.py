#!/home/sail/miniconda2/bin/python
# coding: utf-8

from gevent import monkey, sleep, signal, spawn
monkey.patch_all()  # noqa

import os, sys, logging

logger = logging.getLogger('gnsq_mp')
# logger.addHandler(logging.StreamHandler(sys.stdout))
# # open('gnsq_cluster_%s.log' % os.getpid(), 'a+')
# logger.setLevel(logging.DEBUG)

from random import random

from gnsq import Reader


class NsqProcessWorker(object):

    reader = None
    shutdown_timeout = -1  # seconds bevose
    ppid = os.getppid()

    @classmethod
    def poll_cmd(cls):
        while True:
            yield raw_input()

    def handle_message(self, reader, message):
        raise NotImplementedError()

    @classmethod
    def run_stdin(cls):
        """
        @ToDo: run commands via stdin.
        using sys.argv means static topic/nsqd
        can not be stopped in the middle
        """
        for cmd in cls.poll_cmd():
            func, args = cmd.split()
            # copy some func from http://nsq.io/clients/tcp_protocol_spec.html
            if func.upper() == 'SUB' and cls.reader is None and len(args) == 5:
                cls(args)
            elif func.upper() == 'CLS':
                for conn in cls.reader.conns:
                    conn.close()

    @classmethod
    def run(cls, block=False):
        if len(sys.argv) != 4:
            print>>sys.stderr, "Usage: %s topic channel nsqd_tcp_addr" % __file__
            exit(0)
        signal(2, cls.close)
        args = sys.argv[1:4] + [block]
        logger.info(" [worker_start] start nsq subscriber. pid=%s, args=%s", os.getpid(), args)
        return cls(*args)

    @classmethod
    def check_parent(cls):
        # check original parent pid
        try:
            r = os.kill(cls.ppid, 0)
        except OSError:
            return False
        # if original pid exists and real pid is not 1
        ppid = os.getppid()
        if ppid != cls.ppid:
            return False
        if r is None and ppid > 1:  # zombie/orphan process parent pid==1
            return ppid
        return False

    @classmethod
    def poll_parent(cls):
        while cls.shutdown_timeout < 0 and cls.check_parent():
            sleep(2 + random())
        if cls.shutdown_timeout <= 0:
            cls.close()
        while cls.shutdown_timeout > 0:
            cls.shutdown_timeout -= 1
            sleep(1)
        exit(0)  # force close

    def __init__(self, topic, nsqd_addr, channel, block=False):
        self.nsqd_addr = nsqd_addr
        self.topic = topic
        self.channel = channel
        NsqProcessWorker.reader = Reader(
            topic, channel,
            message_handler=self.handle_message,
            nsqd_tcp_addresses=nsqd_addr,
            max_in_flight=200, max_concurrency=200)
        spawn(self.__class__.poll_parent)
        NsqProcessWorker.reader.start(block)  # because consumer will block

    @classmethod
    def close(cls):
        cls.shutdown_timeout = 8  # 5 seconds timeout
        logger.info(' [worker_close] pid=%s cls=%s, reader=%s', os.getpid(), cls, cls.reader)
        # if cls.reader and cls.reader.conns:
        for conn in cls.reader.conns:
            conn.close()
        # if cls.reader:
        cls.reader.close()


if '__main__' == __name__:
    NsqProcessWorker.run()
