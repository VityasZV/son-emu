"""
Distributed Cloud Emulator (dcemulator)
(c) 2015 by Manuel Peuster <manuel.peuster@upb.de>
"""
from mininet.node import Docker
import logging


DCDPID_BASE = 1000  # start of switch dpid's used for data center switches


class EmulatorCompute(Docker):
    """
    Emulator specific compute node class.
    Inherits from Dockernet's Docker host class.
    Represents a single container connected to a (logical)
    data center.
    We can add emulator specific helper functions to it.
    """

    def __init__(
            self, name, dimage, **kwargs):
        logging.debug("Create EmulatorCompute instance: %s" % name)

        # call original Docker.__init__
        Docker.__init__(self, name, dimage, **kwargs)

    def getNetworkStatus(self):
        """
        Helper method to receive information about the virtual networks
        this compute instance is connected to.
        """
        # format list of tuples (name, Ip, MAC, isUp, status)
        return [(str(i), i.IP(), i.MAC(), i.isUp(), i.status())
                for i in self.intfList()]

    def getStatus(self):
        """
        Helper method to receive information about this compute instance.
        """
        status = {}
        status["name"] = self.name
        status["network"] = self.getNetworkStatus()
        status["image"] = self.dimage
        status["cpu_quota"] = self.cpu_quota
        status["cpu_period"] = self.cpu_period
        status["cpu_shares"] = self.cpu_shares
        status["cpuset"] = self.cpuset
        status["mem_limit"] = self.mem_limit
        status["memswap_limit"] = self.memswap_limit
        status["state"] = self.dcli.inspect_container(self.dc)["State"]
        status["id"] = self.dcli.inspect_container(self.dc)["Id"]
        return status


class Datacenter(object):
    """
    Represents a logical data center to which compute resources
    (Docker containers) can be added at runtime.

    Will also implement resource bookkeeping in later versions.
    """

    def __init__(self, name):
        self.net = None  # DCNetwork to which we belong
        self.name = name
        self.switch = None  # first prototype assumes one "bigswitch" per DC
        self.containers = {}  # keep track of running containers

    def _get_next_dc_dpid(self):
        global DCDPID_BASE
        DCDPID_BASE += 1
        return DCDPID_BASE

    def create(self):
        """
        Each data center is represented by a single switch to which
        compute resources can be connected at run time.

        TODO: This will be changed in the future to support multiple networks
        per data center
        """
        self.switch = self.net.mnet.addSwitch(
            "%s.s1" % self.name, dpid=hex(self._get_next_dc_dpid())[2:])
        logging.debug("created data center switch: %s" % str(self.switch))

    def start(self):
        pass

    def startCompute(self, name, image=None, network=None):
        """
        Create a new container as compute resource and connect it to this
        data center.

        TODO: This interface will change to support multiple networks to which
        a single container can be connected.
        """
        assert name is not None
        # set default parameter
        if image is None:
            image = "ubuntu"
        if network is None:
            network = {}  # {"ip": "10.0.0.254/8"}
        # create the container and connect it to the given network
        d = self.net.addDocker("%s" % (name), dimage=image)
        self.net.addLink(d, self.switch, params1=network)
        self.containers[name] = d
        return name  # we might use UUIDs for naming later on

    def stopCompute(self, name):
        """
        Stop and remove a container from this data center.
        """
        assert name in self.containers
        self.net.removeLink(
            link=None, node1=self.containers[name], node2=self.switch)
        self.net.removeDocker("%s" % (name))
        del self.containers[name]
        return True

    def listCompute(self):
        """
        Return a list of all running containers assigned to this
        data center.
        """
        return self.containers.itervalues()
