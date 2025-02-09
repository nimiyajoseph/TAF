import unittest
import time

from TestInput import TestInputSingleton
from global_vars import logger
from Cb_constants import constants, CbServer
from platform_utils.remote.remote_util import RemoteMachineShellConnection


class ServerInfo:
    def __init__(self,
                 ip,
                 port,
                 ssh_username,
                 ssh_password,
                 memcached_port,
                 ssh_key=''):
        self.ip = ip
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.port = port
        self.rest_username = "Administrator"
        self.rest_password = "password"
        self.ssh_key = ssh_key
        self.memcached_port = memcached_port
        self.remote_info = None


class CGroupBase(unittest.TestCase):
    def setUp(self):
        self.input = TestInputSingleton.input
        self.log_level = self.input.param("log_level", "info").upper()
        self.log = logger.get("test")
        self.infra_log = logger.get("infra")
        self.infra_log_level = self.input.param("infra_log_level",
                                                "error").upper()
        self.log.setLevel(self.log_level)
        self.infra_log.setLevel(self.infra_log_level)
        self.servers = self.input.servers
        self.vm_ip = self.servers[0].ip
        self.rest_port = self.servers[0].port
        self.ssh_username = self.servers[0].ssh_username
        self.ssh_password = "couchbase"
        self.node = ServerInfo(ip=self.vm_ip, port=self.rest_port,
                               ssh_username=self.ssh_username, ssh_password=self.ssh_password,
                               memcached_port=CbServer.memcached_port)
        self.shell = RemoteMachineShellConnection(self.node)
        self.skip_setup_teardown = self.input.param("skip_setup_teardown", None)
        self.skip_teardown = self.input.param("skip_teardown", None)
        self.cb_cpu_count_env = self.input.param("cb_cpu_count_env", None)  # COUCHBASE_CPU_COUNT env
        self.cpus = self.input.param("cpus", 2)  # cpus limit for the container
        self.mem = self.input.param("mem", 1073741824)  # mem limit for the container in bytes

        # Pass service_mem_alloc as service_name1:memory_to_be_allocated-service_name2:memory_to_be_allocated
        service_mem_alloc = self.input.param("service_mem_alloc", None)
        self.service_and_memory_allocation = dict()
        if service_mem_alloc:
            temp = service_mem_alloc.split("-")
            for service in temp:
                temp2 = service.split(":")
                self.service_and_memory_allocation[temp2[0]] = temp2[1]

        if self.skip_setup_teardown is None:
            self.start_docker()
            self.remove_all_containers()
            self.start_couchbase_container(mem=self.mem, cpus=self.cpus)
            self.set_disk_paths()
            self.initialize_node()
        self.log.info("Finished CGroupBase")

    def set_disk_paths(self):
        # Pass service_disk_paths as service_name1:number_of_paths-service_name2:number_of_paths
        service_disk_paths = self.input.param("service_disk_paths", None)
        cmd = "docker exec db /opt/couchbase/bin/couchbase-cli node-init " \
              "-c 127.0.0.1 --username Administrator --password password"
        self.service_disk_paths = dict()
        if service_disk_paths:
            temp = service_disk_paths.split("-")
            for service in temp:
                temp2 = service.split(":")
                if int(temp2[1]) > 1:
                    self.service_disk_paths[temp2[0]] = int(temp2[1])
                    if temp2[0] == "data":
                        path_format = "/opt/couchbase/var/lib/couchbase/data/data{0}"
                        flag = "--node-init-data-path"
                    elif temp2[0] == "index":
                        path_format = "/opt/couchbase/var/lib/couchbase/tmp/index{0}"
                        flag = "--node-init-index-path"
                    elif temp2[0] == "analytics":
                        path_format = "/opt/couchbase/var/lib/couchbase/tmp/analytics{0}"
                        flag = "--node-init-analytics-path"
                    elif temp2[0] == "eventing":
                        path_format = "/opt/couchbase/var/lib/couchbase/tmp/eventing{0}"
                        flag = "--node-init-eventing-path"
                    for p in range(int(temp2[1])):
                        cmd += " {0} ".format(flag) + path_format.format(p)
                else:
                    self.service_disk_paths[temp2[0]] = 1
            self.log.info("Setting disk path")
            self.log.debug("CMD to set disk path : %s" % cmd)
            o, e = self.shell.execute_command(cmd)
            self.log.info("Output:{0}, Error{1}".format(o, e))

    def initialize_node(self, sleep=15):
        self.log.info("initializing the node")
        cmd = "docker exec db " \
              "/opt/couchbase/bin/couchbase-cli cluster-init -c 127.0.0.1 --cluster-username Administrator " \
              "--cluster-password password "
        if self.service_and_memory_allocation:
            services = ",".join(self.service_and_memory_allocation.keys())
            memory_allocations = ""
            for service, memory in self.service_and_memory_allocation.iteritems():
                if service == "data":
                    memory_allocations += "--cluster-ramsize {0} ".format(memory)
                elif service == "index":
                    memory_allocations += "--cluster-index-ramsize {0} ".format(memory)
                elif service == "fts":
                    memory_allocations += "--cluster-fts-ramsize {0} ".format(memory)
                elif service == "eventing":
                    memory_allocations += "--cluster-eventing-ramsize {0} ".format(memory)
                elif service == "analytics":
                    memory_allocations += "--cluster-analytics-ramsize {0} ".format(memory)
            cmd += "--services {0} {1}".format(services, memory_allocations)
        else:
            cmd += "--services data --cluster-ramsize 500"

        o, e = self.shell.execute_command(cmd)
        self.log.info("Docker command run: {0}".format(cmd))
        self.log.info("Output:{0}, Error{1}".format(o, e))
        self.log.info("Sleeping for {0} secs post initializing".format(sleep))
        time.sleep(sleep)

    def start_docker(self):
        self.log.info("Starting docker")
        cmd = "systemctl start docker"
        o, e = self.shell.execute_command(cmd)
        self.log.info("Output:{0}, Error{1}".format(o, e))

    def start_couchbase_container(self, mem=1073741824, cpus=2, sleep=20):
        """
        Starts couchbase server inside a container on the VM
        (Assumes a docker image 'couchbase-neo' is present on the VM)
        :limits: Boolean - whether to start the container with memory & cpu limits
        :mem: int - max memory in bytes for the container
        :cpus: int - max number of cpus for the container
        """
        self.log.info("Starting couchbase server inside a container")
        flags = ""
        if self.mem not in [None, "None"]:
            flags = flags + "-m " + str(mem) + "b"
        if self.cpus not in [None, "None"]:
            flags = flags + " --cpus " + str(cpus)
        if self.cb_cpu_count_env not in [None, "None"]:
            flags = flags + " -e COUCHBASE_CPU_COUNT=" + str(self.cb_cpu_count_env)
        cmd = "docker run -d -t --name db " + flags + \
              " -p 8091-8096:8091-8096 -p 11210-11211:11210-11211 couchbase-neo"
        o, e = self.shell.execute_command(cmd)
        self.log.info("Docker command run: {0}".format(cmd))
        self.log.info("Output:{0}, Error{1}".format(o, e))
        self.log.info("Sleeping for {0} secs post starting couchbase container".format(sleep))
        time.sleep(sleep)

    def remove_all_containers(self):
        self.log.info("Stopping all containers")
        cmd = "docker stop $(docker ps -a -q)"
        o, e = self.shell.execute_command(cmd)
        self.log.info("Output:{0}, Error{1}".format(o, e))
        self.log.info("Removing all containers")
        cmd = "docker rm $(docker ps -a -q)"
        o, e = self.shell.execute_command(cmd)
        self.log.info("Output:{0}, Error{1}".format(o, e))

    def tearDown(self):
        self.shell.disconnect()
        if self.skip_teardown is None:
            self.remove_all_containers()

    def update_container_cpu_limit(self, cpus):
        """
        Updates cpu cores limit of a running docker container
        :cpus: cpu cores limit
        """
        self.log.info("Updating the running container's cpu cores limit from {0} to {1}".
                      format(self.cpus, cpus))
        cmd = "docker update --cpus " + str(cpus) + "  db"
        o, e = self.shell.execute_command(cmd)
        print(o, e)
        self.cpus = cpus

    def restart_server(self):
        self.log.info("Stopping and starting server...")
        self.shell.execute_command("docker exec db service couchbase-server stop")
        time.sleep(10)
        self.shell.execute_command("docker exec db service couchbase-server start")
        time.sleep(20)
