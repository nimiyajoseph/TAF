"""
Created on Feb 16, 2022

@author: ritesh.agarwal
"""
import json

from BucketLib.bucket import Bucket
from Cb_constants import CbServer
from TestInput import TestInputSingleton, TestInputServer
from bucket_utils.bucket_ready_functions import BucketUtils
from capella.capella_utils import CapellaUtils as CapellaAPI
from capella.capella_utils import Pod, Tenant
from cb_basetest import CouchbaseBaseTest
from cluster_utils.cluster_ready_functions import ClusterUtils, CBCluster
from constants.cloud_constants.capella_constants import AWS, Cluster
from security_config import trust_all_certs
from Jython_tasks.task import DeployCloud


class OnCloudBaseTest(CouchbaseBaseTest):
    def setUp(self):
        super(OnCloudBaseTest, self).setUp()

        # Framework specific parameters
        for server in self.input.servers:
            server.hosted_on_cloud = True
        # End of framework parameters

        # Cluster level info settings
        self.servers = list()
        self.capella = self.input.capella
        self.num_clusters = self.input.param("num_clusters", 1)

        # Bucket specific params
        # Note: Over riding bucket_eviction_policy from CouchbaseBaseTest
        self.bucket_eviction_policy = \
            self.input.param("bucket_eviction_policy",
                             Bucket.EvictionPolicy.FULL_EVICTION)
        # End of bucket parameters

        # Doc Loader Params (Extension from cb_basetest)
        self.delete_docs_at_end = self.input.param(
            "delete_doc_at_end", True)
        # End of client specific parameters

        self.wait_timeout = self.input.param("wait_timeout", 120)
        self.use_https = self.input.param("use_https", True)
        self.enforce_tls = self.input.param("enforce_tls", True)
        self.ipv4_only = self.input.param("ipv4_only", False)
        self.ipv6_only = self.input.param("ipv6_only", False)
        self.multiple_ca = self.input.param("multiple_ca", False)
        CbServer.use_https = True
        trust_all_certs()

        # initialise pod object
        url = self.input.capella.get("pod")
        self.pod = Pod("https://%s" % url)

        self.tenant = Tenant(self.input.capella.get("tenant_id"),
                             self.input.capella.get("capella_user"),
                             self.input.capella.get("capella_pwd"),
                             self.input.capella.get("secret_key"),
                             self.input.capella.get("access_key"))

        '''
        Be careful while using this flag.
        This is only and only for stand-alone tests.
        During bugs reproductions, when a crash is seen
        stop_server_on_crash will stop the server
        so that we can collect data/logs/dumps at the right time
        '''
        self.stop_server_on_crash = self.input.param("stop_server_on_crash",
                                                     False)
        self.collect_data = self.input.param("collect_data", False)
        self.validate_system_event_logs = \
            self.input.param("validate_sys_event_logs", False)

        self.nonroot = False
        self.crash_warning = self.input.param("crash_warning", False)
        self.rest_username = \
            TestInputSingleton.input.membase_settings.rest_username
        self.rest_password = \
            TestInputSingleton.input.membase_settings.rest_password

        self.log_setup_status(self.__class__.__name__, "started")
        self.cluster_name_format = "C%s"
        default_cluster_index = cluster_index = 1
        self.capella_cluster_config = CapellaAPI.get_cluster_config(
            environment="hosted",
            description="Amazing Cloud",
            single_az=False,
            provider=self.input.param("provider", AWS.__str__).lower(),
            region=self.input.param("region", AWS.Region.US_WEST_2),
            timezone=Cluster.Timezone.PT,
            plan=Cluster.Plan.DEV_PRO,
            cluster_name="taf_cluster")

        services = self.input.param("services", "data")
        for service_group in services.split("-"):
            service_group = service_group.split(":")
            min_nodes = 3 if "data" in service_group else 2
            service_config = CapellaAPI.get_cluster_config_spec(
                services=service_group,
                count=max(min_nodes, self.nodes_init),
                compute=self.input.param("compute",
                                         AWS.ComputeNode.VCPU4_RAM16),
                storage_type=self.input.param("type", AWS.StorageType.GP3),
                storage_size_gb=self.input.param("size", AWS.StorageSize.MIN),
                storage_iops=self.input.param("iops", AWS.StorageIOPS.MIN))
            if self.capella_cluster_config["place"]["hosted"]["provider"] \
                    != AWS.__str__:
                service_config["storage"].pop("iops")
            self.capella_cluster_config["servers"].append(service_config)

        self.tenant.project_id = \
            TestInputSingleton.input.capella.get("project", None)
        if not self.tenant.project_id:
            CapellaAPI.create_project(self.pod, self.tenant, "a_taf_run")

        # Comma separated cluster_ids [Eg: 123-456-789,111-222-333,..]
        cluster_ids = TestInputSingleton.input.capella \
            .get("clusters", "")
        if cluster_ids:
            cluster_ids = cluster_ids.split(",")
            self.__get_existing_cluster_details(cluster_ids)
        else:
            tasks = list()
            for _ in range(self.num_clusters):
                cluster_name = self.cluster_name_format % cluster_index
                self.capella_cluster_config["clusterName"] = \
                    "a_%s_%s_%sGB_%s" % (
                        self.input.param("provider", "aws"),
                        self.input.param("compute", "m5.xlarge")
                            .replace(".", ""),
                        self.input.param("size", 50),
                        cluster_name)
                self.log.info(self.capella_cluster_config)
                deploy_task = DeployCloud(self.pod, self.tenant, cluster_name,
                                          self.capella_cluster_config)
                self.task_manager.add_new_task(deploy_task)
                tasks.append(deploy_task)
                cluster_index += 1
            for task in tasks:
                self.task_manager.get_task_result(task)
                self.assertTrue(task.result, "Cluster deployment failed!")
                CapellaAPI.create_db_user(
                    self.pod, self.tenant, task.cluster_id,
                    self.rest_username, self.rest_password)
                self.__populate_cluster_info(task.cluster_id, task.servers,
                                             task.srv, task.name,
                                             self.capella_cluster_config)

        # Initialize self.cluster with first available cluster as default
        self.cluster = self.cb_clusters[self.cluster_name_format
                                        % default_cluster_index]
        self.servers = self.cluster.servers
        self.cluster_util = ClusterUtils(self.task_manager)
        self.bucket_util = BucketUtils(self.cluster_util, self.task)
        for _, cluster in self.cb_clusters.items():
            self.cluster_util.print_cluster_stats(cluster)

        self.cluster.edition = "enterprise"
        self.sleep(10)

    def tearDown(self):
        self.shutdown_task_manager()
        if self.sdk_client_pool:
            self.sdk_client_pool.shutdown()

        if self.skip_teardown_cleanup:
            return

        for name, cluster in self.cb_clusters.items():
            self.log.info("Destroying cluster: {}".format(name))
            CapellaAPI.destroy_cluster(cluster)
        CapellaAPI.delete_project(self.pod, self.tenant)

    def __get_existing_cluster_details(self, cluster_ids):
        cluster_index = 1
        for cluster_id in cluster_ids:
            cluster_name = self.cluster_name_format % cluster_index
            self.log.info("Fetching cluster details for: %s" % cluster_id)
            CapellaAPI.wait_until_done(self.pod, self.tenant, cluster_id,
                                       "Cluster not healthy")
            cluster_info = CapellaAPI.get_cluster_info(self.pod, self.tenant,
                                                       cluster_id)
            cluster_srv = cluster_info.get("endpointsSrv")
            CapellaAPI.add_allowed_ip(self.pod, self.tenant, cluster_id)
            CapellaAPI.create_db_user(
                    self.pod, self.tenant, cluster_id,
                    self.rest_username, self.rest_password)
            servers = CapellaAPI.get_nodes(self.pod, self.tenant, cluster_id)
            self.__populate_cluster_info(cluster_id, servers, cluster_srv,
                                         cluster_name, cluster_info)
            self.__populate_cluster_buckets(self.cb_clusters[cluster_name])

    def __populate_cluster_info(self, cluster_id, servers, cluster_srv,
                                cluster_name, service_config):
        nodes = list()
        for server in servers:
            temp_server = TestInputServer()
            temp_server.ip = server.get("hostname")
            temp_server.hostname = server.get("hostname")
            temp_server.services = server.get("services")
            temp_server.port = "18091"
            temp_server.rest_username = self.rest_username
            temp_server.rest_password = self.rest_password
            temp_server.hosted_on_cloud = True
            temp_server.memcached_port = "11207"
            nodes.append(temp_server)
        cluster = CBCluster(username=self.rest_username,
                            password=self.rest_password,
                            servers=[None] * 40)
        cluster.id = cluster_id
        cluster.srv = cluster_srv
        cluster.cluster_config = service_config
        cluster.pod = self.pod
        cluster.tenant = self.tenant

        for temp_server in nodes:
            if "Data" in temp_server.services:
                cluster.kv_nodes.append(temp_server)
            if "Query" in temp_server.services:
                cluster.query_nodes.append(temp_server)
            if "Index" in temp_server.services:
                cluster.index_nodes.append(temp_server)
            if "Eventing" in temp_server.services:
                cluster.eventing_nodes.append(temp_server)
            if "Analytics" in temp_server.services:
                cluster.cbas_nodes.append(temp_server)
            if "FTS" in temp_server.services:
                cluster.fts_nodes.append(temp_server)
        cluster.master = cluster.kv_nodes[0]
        self.tenant.clusters.update({cluster.id: cluster})

        cluster.master = cluster.kv_nodes[0]
        self.tenant.clusters.update({cluster.id: cluster})
        self.cb_clusters[cluster_name] = cluster
        self.cb_clusters[cluster_name].cloud_cluster = True

    def __populate_cluster_buckets(self, cluster):
        self.log.debug("Fetching bucket details from cluster %s" % cluster.id)
        buckets = json.loads(CapellaAPI.get_all_buckets(cluster)
                             .content)["buckets"]["data"]
        for bucket in buckets:
            bucket = bucket["data"]
            bucket_obj = Bucket({
                Bucket.name: bucket["name"],
                Bucket.ramQuotaMB: bucket["memoryAllocationInMb"],
                Bucket.replicaNumber: bucket["replicas"],
                Bucket.conflictResolutionType:
                    bucket["bucketConflictResolution"],
                Bucket.flushEnabled: bucket["flush"],
                Bucket.durabilityMinLevel: bucket["durabilityLevel"],
                Bucket.maxTTL: bucket["timeToLive"],
            })
            bucket_obj.uuid = bucket["id"]
            bucket_obj.stats.itemCount = bucket["stats"]["itemCount"]
            bucket_obj.stats.memUsed = bucket["stats"]["memoryUsedInMib"]
            cluster.buckets.append(bucket_obj)


class ClusterSetup(OnCloudBaseTest):
    def setUp(self):
        super(ClusterSetup, self).setUp()

        self.log_setup_status("ClusterSetup", "started", "setup")

        # Print cluster stats
        self.cluster_util.print_cluster_stats(self.cluster)
        self.log_setup_status("ClusterSetup", "complete", "setup")

    def tearDown(self):
        super(ClusterSetup, self).tearDown()
