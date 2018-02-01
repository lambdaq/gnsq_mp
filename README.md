# gnsq_mp

NSQ with multi process Gevent.

Due the limitations of GIL in CPython, event with Gevent, [`gnsq`](https://github.com/wtolson/gnsq/) can not handle high-volumn message.

If we spawn multi consumer process for each topic, as the process number grows, so does the TCP connection established to each nsqd host.

This `gnsq_mp` project implements a multiprocess mode:

 - the `NsqMPController` process polls and spawns sub-process for individuale nsqd connections
 - the `NsqProcessWorker` sub-process connects to a single nsqd host and consumes message
 - sub-process are health-checked and automatically restarted if exits unexpectedly
 - sub-process will exit if became a orphan
 - sub-processes are by default set CPU affilinty with only 1 processor core.


# Usage:

First of all, create your `worker.py` like this:

    
    from gnsq_mp import NsqProcessWorker

    class MyWorker(NsqProcessWorker):

        def handle_message(self, reader, message):
            print (message.body)

    if '__main__' == __name__:
        MyWorker.run(block=True)


Note the `worker.py` will be launched as a deparate process with parameters `topic`, `nsqd_addr` and `channel_name`. You should be able to test the script directly in shell.


Then create a master which spawns the `worker.py` dynamically with nsqlookupd results.

The source code should look like:


    from gnsq_mp import NsqMPController

    class MyController(NsqMPController):
        lookupd_http_addresses = [
            "http://10.1.1.1:4161",
            "http://10.1.1.2:4161",
            "http://10.1.1.3:4161",
        ]
        worker = 'worker.py'  # relative path to the script you created above

    MyController.run(topic="blah", channel_name="gnsq_mp#ephemeral")

