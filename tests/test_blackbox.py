"""Assume behaviour on part of the core Pyblish library"""

import sys

import pyblish_rpc.client
import pyblish_rpc.server

import pyblish.api
import pyblish.lib
import pyblish.logic

from nose.tools import (
    with_setup,
    assert_equals,
    assert_false,
    assert_true
)

server = None
thread = None
process = None
client = None
port = 6000

self = sys.modules[__name__]


def setup():
    """Threaded RPC server

    The benefit of a threaded server is that we can introspect
    and register plug-ins during a test that is then used in
    the test by the RPC client.

    """

    import threading
    import pyblish_rpc.server
    import pyblish_rpc.service

    service = pyblish_rpc.service.RpcService()
    self.server = pyblish_rpc.server._server(port, service)
    self.thread = threading.Thread(target=self.server.serve_forever)
    self.thread.daemon = True
    self.thread.start()
    self.host = pyblish_rpc.client.Proxy(port)


def teardown():
    self.server.shutdown()
    self.thread.join(timeout=10)
    assert not thread.isAlive()


def setup_empty():
    """Clear Pyblish of all possible external stimuli"""
    pyblish.api.deregister_all_paths()
    pyblish.api.deregister_all_plugins()
    pyblish.api.deregister_all_services()

    self.host.reset()


class Controller(object):
    """A minimal Pyblish QML controller"""
    def __init__(self, port):
        self.api = pyblish_rpc.client.Proxy(port)
        self.plugins = list()

    def reset(self):
        self.api.reset()
        self.plugins = self.api.discover()

        results = list()
        plugins = [
            p for p in self.plugins
            if pyblish.lib.inrange(
                number=p.order,
                base=pyblish.api.CollectorOrder)
        ]

        for result in pyblish.logic.process(
                func=self.api.process,
                plugins=plugins,
                context=self.api.context):
            results.append(result)

        return results
    
    def _process(self, func):
        results = list()
        plugins = [
            p for p in self.plugins
            if not pyblish.lib.inrange(
                number=p.order,
                base=pyblish.api.CollectorOrder)
        ]

        context = self.api.context()
        print("Processing: %s, %s" % (context, plugins))

        for result in pyblish.logic.process(
                func=func,
                plugins=plugins,
                context=context):
    
            if isinstance(result, pyblish.logic.TestFailed):
                print("Stopped due to: %s" % result)
                break

            if isinstance(result, Exception):
                print("publish(): Got an unexpected exception: %s" % result)
                break

            results.append(result)
        return results

    def publish(self):
        self._process(self.api.process)

    @pyblish.lib.deprecated
    def repair(self):
         self._process(self.api.repair)


@with_setup(setup_empty)
def test_mock_client():
    """A mock client works fine"""
    count = {"#": 0}
    instances = list()

    assert_equals(pyblish.api.registered_plugins(), [])

    class SelectInstances(pyblish.api.Selector):
        def process(self, context):
            print("Processing %s" % type(self).__name__)
            instance = context.create_instance("MyInstance")
            instances.append(instance)
            instance.set_data("family", "myFamily")
            instance.data["marcus"] = "Marcus"
            count["#"] += 1

    class ValidateInstances(pyblish.api.Validator):
        families = ["myFamily"]

        def process(self, instance):
            print("Processing %s" % type(self).__name__)
            count["#"] += 1
            assert False

    pyblish.api.register_plugin(SelectInstances)
    pyblish.api.register_plugin(ValidateInstances)

    c = Controller(port)
    c.reset()

    assert_equals(
        list(i.id for i in c.api.context()),
        list(i.id for i in instances), (
            "Local ids differs from Remote"))

    assert_equals(
        list(i.data["family"] for i in c.api.context()),
        list(i.data["family"] for i in instances), (
            "Local instances differs from Remote"))

    plugins = c.api.discover()

    assert SelectInstances.id in [p.id for p in plugins]
    assert ValidateInstances.id in [p.id for p in plugins]
    assert ValidateInstances.id in [p.id for p in c.plugins], (
        "Plug-in not available in the host")

    c.publish()

    instance = c.api.context()[0]
    assert_equals(instance.name, "MyInstance")
    assert_equals(count["#"], 2)
    assert_true(c.api.stats()["totalRequestCount"] > 0)


def test_ping():
    """Pinging server works well"""
    message = self.host.ping()
    assert_true(message)


@with_setup(setup_empty)
def test_logic():
    """Logic works well"""
    count = {"#": 0, "failed": False}

    assert_equals(pyblish.api.registered_plugins(), [])

    class RunOnce(pyblish.api.Selector):
        def process(self, context):
            print("Processing: %s" % type(self).__name__)

            for name in ("A", "B"):
                instance = context.create_instance(name)
                instance.set_data("family", "myFamily")

            count["#"] += 1

    class RunTwice(pyblish.api.Validator):
        """This supports the family of both instances"""
        families = ["myFamily"]

        def process(self, instance):
            print("Processing: %s" % type(self).__name__)
            count["#"] += 10

            count["failed"] = True
            assert False, "I was programmed to fail"

    class DontRun1(pyblish.api.Validator):
        """This isn't run, because of an unsupported family"""
        families = ["unsupportedFamily"]

        def process(self, instance):
            print("Processing: %s" % type(self).__name__)
            count["#"] += 100

    class DontRun2(pyblish.api.Extractor):
        """This isn't run, because validation fails above"""
        def process(self, context):
            print("Processing: %s" % type(self).__name__)
            count["#"] += 1000

    class DontRun3(pyblish.api.Extractor):
        """This isn't run, because validation fails above"""
        families = ["myFamily"]

        def process(self, instance):
            print("Processing: %s" % type(self).__name__)
            count["#"] += 10000

    pyblish.api.register_plugin(RunOnce)
    pyblish.api.register_plugin(RunTwice)
    pyblish.api.register_plugin(DontRun1)
    pyblish.api.register_plugin(DontRun2)
    pyblish.api.register_plugin(DontRun3)

    c = Controller(port)
    c.reset()
    c.publish()

    context = self.host.context()
    assert context[0].name in ["A", "B"]
    assert context[1].name in ["A", "B"]
    assert_equals(count["#"], 21)
    assert_true(count["failed"])


@with_setup(setup_empty)
def test_repair():
    """Repairing with DI works well"""

    _data = {}

    class SelectInstance(pyblish.api.Selector):
        def process(self, context):
            print("Running %s" % type(self))
            instance = context.create_instance("MyInstance")
            instance.set_data("family", "MyFamily")

    class ValidateInstance(pyblish.api.Validator):
        def process(self, instance):
            _data["broken"] = True
            assert False, "Broken"

        def repair(self, instance):
            _data["broken"] = False

    for plugin in (SelectInstance, ValidateInstance):
        pyblish.api.register_plugin(plugin)

    c = Controller(port)
    c.reset()
    c.publish()

    assert_true(_data["broken"])

    c.repair()

    assert_false(_data["broken"])


@with_setup(setup_empty)
def test_logging_nonstring():
    """Logging a non-string message is ok"""

    class SelectInstance(pyblish.api.Selector):
        def process(self, context):
            self.log.info("This is ok")
            self.log.info(None)
            self.log.info(str)

    pyblish.api.register_plugin(SelectInstance)

    for result in pyblish.logic.process(
            func=self.host.process,
            plugins=self.host.discover,
            context=self.host.context):

        message = result["records"][0]["message"]
        assert message in ("This is ok",
                           "None",
                           "<type 'str'>"), message


@with_setup(setup_empty)
def test_emit_implicit_conversion():
    """Emitting via service implicitly converts instances to objects"""

    count = {"#": 0}
    instances = []

    class MyCollector(pyblish.api.Collector):
        def process(self, context):
            count["#"] += 1

            instance = context.create_instance("MyInstance")
            instances.append(instance)

    def callback(instance, plugin, context, not_converted):
        assert isinstance(instance, pyblish.api.Instance), (
            "Passed instance was not implicitly converted")
        assert isinstance(context, pyblish.api.Context), (
            "Passed instance was not implicitly converted")
        assert issubclass(plugin, pyblish.api.Collector), (
            "Passed plugin was not implicitly converted")
        assert isinstance(not_converted, basestring)
        count["#"] += 10

    pyblish.api.register_callback("myEvent", callback)
    pyblish.api.register_plugin(MyCollector)

    c = Controller(port)
    c.reset()
    c.publish()

    self.host.emit("myEvent",
                   instance=instances[0].id,
                   plugin=MyCollector.id,
                   context=None,
                   not_converted="Test")

    assert count["#"] == 11
