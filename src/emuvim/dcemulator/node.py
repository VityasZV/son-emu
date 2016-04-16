"""
Distributed Cloud Emulator (dcemulator)
(c) 2015 by Manuel Peuster <manuel.peuster@upb.de>
"""
from mininet.node import Docker
from mininet.link import Link
import logging
import time
import json

LOG = logging.getLogger("dcemulator")
LOG.setLevel(logging.DEBUG)


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
        self.datacenter = kwargs.get("datacenter")  # pointer to current DC
        self.flavor_name = kwargs.get("flavor_name")
        LOG.debug("Starting compute instance %r in data center %r" % (name, str(self.datacenter)))
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
        status["datacenter"] = (None if self.datacenter is None
                                else self.datacenter.label)
        return status


class Datacenter(object):
    """
    Represents a logical data center to which compute resources
    (Docker containers) can be added at runtime.

    Will also implement resource bookkeeping in later versions.
    """

    DC_COUNTER = 1

    def __init__(self, label, metadata={}, resource_log_path=None):
        self.net = None  # DCNetwork to which we belong
        # each node (DC) has a short internal name used by Mininet
        # this is caused by Mininets naming limitations for swtiches etc.
        self.name = "dc%d" % Datacenter.DC_COUNTER
        Datacenter.DC_COUNTER += 1
        # use this for user defined names that can be longer than self.name
        self.label = label  
        # dict to store arbitrary metadata (e.g. latitude and longitude)
        self.metadata = metadata
        # path to which resource information should be logged (e.g. for experiments). None = no logging
        self.resource_log_path = resource_log_path
        # first prototype assumes one "bigswitch" per DC
        self.switch = None
        # keep track of running containers
        self.containers = {}
        # pointer to assigned resource model
        self._resource_model = None

    def __repr__(self):
        return self.label

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
        self.switch = self.net.addSwitch(
            "%s.s1" % self.name, dpid=hex(self._get_next_dc_dpid())[2:])
        LOG.debug("created data center switch: %s" % str(self.switch))

    def start(self):
        pass

    def startCompute(self, name, image=None, command=None, network=None, flavor_name="tiny"):
        """
        Create a new container as compute resource and connect it to this
        data center.
        :param name: name (string)
        :param image: image name (string)
        :param command: command (string)
        :param network: networks list({"ip": "10.0.0.254/8"}, {"ip": "11.0.0.254/24"})
        :param flavor_name: name of the flavor for this compute container
        :return:
        """
        assert name is not None
        # no duplications
        if name in [c.name for c in self.net.getAllContainers()]:
            raise Exception("Container with name %s already exists." % name)
        # set default parameter
        if image is None:
            image = "ubuntu"
        if network is None:
            network = {}  # {"ip": "10.0.0.254/8"}
        if isinstance(network, dict):
            network = [network]  # if we have only one network, put it in a list
        if isinstance(network, list):
            if len(network) < 1:
                network.append({})

        """
        # allocate in resource resource model and compute resource limits for new container
        cpu_limit = mem_limit = disk_limit = -1
        cpu_period = cpu_quota = None
        if self._resource_model is not None:
            # call allocate in resource model to calculate resource limit for this container
            (cpu_limit, mem_limit, disk_limit) = alloc = self._resource_model.allocate(name, flavor_name)
            LOG.debug("Allocation result: %r" % str(alloc))
            # check if we have a cpu_limit given by the used resource model
            if cpu_limit > 0:
                # calculate cpu period and quota for CFS
                # (see: https://www.kernel.org/doc/Documentation/scheduler/sched-bwc.txt)
                # TODO consider multi core machines etc! non trivial!
                # Attention minimum cpu_quota is 1ms (micro)
                cpu_period = 100000  # lets consider a fixed period of 100000 microseconds for now
                cpu_quota = cpu_period * cpu_limit  # calculate the fraction of cpu time for this container
                LOG.debug(
                    "CPU limit: cpu_quota = cpu_period * cpu_limit = %f * %f = %f" % (cpu_period, cpu_limit, cpu_quota))
                # ATTENTION >= 1000 to avoid a invalid argument system error ... no idea why
                if cpu_quota < 1000:
                    cpu_quota = 1000
                    LOG.warning("Increased CPU quota for %r to avoid system error." % name)
            # check if we have a mem_limit given by the used resource model
            if mem_limit > 0:
                LOG.debug(
                    "MEM limit: mem_limit = %f MB" % mem_limit)
                # ATTENTION minimum mem_limit per container is 4MB
                if mem_limit < 4:
                    mem_limit = 4
                    LOG.warning("Increased MEM limit for %r because it was less than 4.0 MB." % name)
        """
        # create the container
        d = self.net.addDocker(
            "%s" % (name),
            dimage=image,
            dcmd=command,
            datacenter=self,
            flavor_name=flavor_name
        )

        # apply resource limits to container if a resource model is defined
        if self._resource_model is not None:
            self._resource_model.allocate(d)

        # connect all given networks
        # if no --net option is given, network = [{}], so 1 empty dict in the list
        # this results in 1 default interface with a default ip address
        for nw in network:
            # TODO we cannot use TCLink here (see: https://github.com/mpeuster/dockernet/issues/3)
            self.net.addLink(d, self.switch, params1=nw, cls=Link)
        # do bookkeeping
        self.containers[name] = d

        # TODO re-enable logging
        """
        # write resource log if a path is given
        if self.resource_log_path is not None:
            l = dict()
            l["t"] = time.time()
            l["name"] = name
            l["compute"] = d.getStatus()
            l["flavor_name"] = flavor_name
            l["action"] = "allocate"
            l["cpu_limit"] = cpu_limit
            l["mem_limit"] = mem_limit
            l["disk_limit"] = disk_limit
            l["rm_state"] = None if self._resource_model is None else self._resource_model.get_state_dict()
            # append to logfile
            with open(self.resource_log_path, "a") as f:
                f.write("%s\n" % json.dumps(l))
        """
        return d  # we might use UUIDs for naming later on

    def stopCompute(self, name):
        """
        Stop and remove a container from this data center.
        """
        assert name is not None
        if name not in self.containers:
            raise Exception("Container with name %s not found." % name)
        LOG.debug("Stopping compute instance %r in data center %r" % (name, str(self)))

        # call resource model and free resources
        if self._resource_model is not None:
            self._resource_model.free(self.containers[name])

        # remove links
        self.net.removeLink(
            link=None, node1=self.containers[name], node2=self.switch)

        # remove container
        self.net.removeDocker("%s" % (name))
        del self.containers[name]

        # TODO re-enable logging
        """
        # write resource log if a path is given
        if self.resource_log_path is not None:
            l = dict()
            l["t"] = time.time()
            l["name"] = name
            l["flavor_name"] = None
            l["action"] = "free"
            l["cpu_limit"] = -1
            l["mem_limit"] = -1
            l["disk_limit"] = -1
            l["rm_state"] = None if self._resource_model is None else self._resource_model.get_state_dict()
            # append to logfile
            with open(self.resource_log_path, "a") as f:
                f.write("%s\n" % json.dumps(l))
        """
        return True

    def listCompute(self):
        """
        Return a list of all running containers assigned to this
        data center.
        """
        return list(self.containers.itervalues())

    def getStatus(self):
        """
        Return a dict with status information about this DC.
        """
        return {
            "label": self.label,
            "internalname": self.name,
            "switch": self.switch.name,
            "n_running_containers": len(self.containers),
            "metadata": self.metadata
        }

    def assignResourceModel(self, rm):
        """
        Assign a resource model to this DC.
        :param rm: a BaseResourceModel object
        :return:
        """
        if self._resource_model is not None:
            raise Exception("There is already an resource model assigned to this DC.")
        self._resource_model = rm
        self.net.rm_registrar.register(self, rm)
        LOG.info("Assigned RM: %r to DC: %r" % (rm, self))

