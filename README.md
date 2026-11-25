# gnsq_mp

![233](https://img.shields.io/badge/🔥-Blazing%20Fast-red.svg)
![233](https://img.shields.io/badge/😿-For%20Near%20Humans-blue.svg)
![233](https://img.shields.io/badge/🏢-Enterprise%20Grade-999999.svg)
![233](https://img.shields.io/badge/👌-Production%20Ready-00ddcc.svg)
![233](https://img.shields.io/badge/💎-Modern-44aadd.svg)
![233](https://img.shields.io/badge/🦋-Extremely%20Lightweight-7799cc.svg)
![233](https://img.shields.io/badge/🔐-Looks%20Secure-yellow.svg)
![233](https://img.shields.io/badge/🐛-Fatal%20Bug%20Free-green.svg)
![233](https://img.shields.io/badge/🦄-Just%20Works-cc00cc.svg)


NSQ with multi process Gevent.

[NSQ](https://nsq.io) is a distrbuted message queue.

[gnsq](https://github.com/wtolson/gnsq/) is a [Gevent](http://www.gevent.org/) powered NSQ library written in pure Python with fast asyncronous operations

Due the limitations of GIL in CPython, even with Gevent, `gnsq` can not handle high-volumn message with many topics and nsqd hosts. It's easy to hit 100% CPU usage for one core.

If we add number of consumer nodes for each topic, as the process number grows, so does the TCP connection established to each nsqd host. It's easy to hit tens of thousands of connections which adds a non-neglectable amount of coroutine context switch cost.

This `gnsq_mp` project implements a new multiprocess mode:

 - the `NsqMPController` process polls [lookupd](nsq.io/components/nsqlookupd.html) and spawns sub-process for each individuale nsqd connections.
 - the `NsqProcessWorker` sub-process connects to a single nsqd host and consumes message
 - sub-process are health-checked and automatically restarted if exits unexpectedly
 - sub-process will exit if became a orphan
 - sub-processes are by default pinned (Linux) to a single CPU core, spread evenly with only 1 processor core.


# Usage

First of all, create your `worker.py` like this:

    from gnsq_mp import NsqProcessWorker

    class MyWorker(NsqProcessWorker):
        max_in_flight = 200            # optional, default 200
        consumer_options = {}          # optional, extra kwargs for gnsq.Consumer

        def handle_message(self, consumer, message):
            print(message.body)        # finished on return, requeued on exception

    if __name__ == '__main__':
        MyWorker.run()

Note: importing `gnsq_mp.worker` monkey patches the stdlib with gevent, so only import it from the worker script.

The script is launched as a separate process with the arguments `topic nsqd_tcp_addr channel [extra_args ...]`. You can run it directly in a shell to test it.

Then create a controller which spawns the `worker.py` dynamically with nsqlookupd results:

    from gnsq_mp import NsqMPController

    class MyController(NsqMPController):
        lookupd_http_addresses = [
            "http://10.1.1.1:4161",
            "http://10.1.1.2:4161",
            "http://10.1.1.3:4161",
        ]
        worker = 'worker.py'  # relative to the file defining the controller

    MyController.run(topic="blah", channel_name="gnsq_mp#ephemeral")

`run()` accepts:

 - `max_procs`: max number of worker processes, `0` (default) for no limit. Running workers are kept first.
 - `extra_args`: list of extra command line arguments passed to every worker (available as `self.extra_args` in the worker).

Tunables, as class attributes of the controller: `poll_interval` (5s), `lookup_interval` (30s), `restart_delay` (5s), `stop_timeout` (15s), `pin_cpu` (True, Linux only), `python_executable`.

`SIGINT`/`SIGTERM` to the controller stops all workers gracefully (workers get `SIGTERM`, then `SIGKILL` after `stop_timeout`).

# Install

    pip install gnsq_mp

Requires Python 3.7+, `gnsq>=1.0` and `gevent`.

# License

BSD 3-clause. See `LICENSE` file.
