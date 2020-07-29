import copy

from magma_base import MagmaBaseTest
from magma_basic_crud import BasicCrudTests



class BasicDeleteTests(BasicCrudTests):
    def test_create_delete_n_times(self):
        """
        STEPS:
           -- Create n items
           -- Delete all n items
           -- Check Space Amplification
           -- Repeat above step n times
        """
        self.log.info("test_create_delete_n_times starts ")

        msg_stats = "Fragmentation value for {} stats exceeds\
        the configured value"

        self.delete_start = 0
        self.delete_end = self.num_items
        self.generate_docs(doc_ops="delete")
        count = 0
        while count < self.test_itr:
            #######################################################################
            '''
            STEP - 1, Delete all the items

            '''
            self.log.debug("Step 1, Iteration= {}".format(count+1))
            self.doc_ops = "delete"
            _ = self.loadgen_docs(self.retry_exceptions,
                                  self.ignore_exceptions,
                                  _sync=True)
            self.bucket_util._wait_for_stats_all_buckets()
            self.bucket_util.verify_stats_all_buckets(self.num_items)

            ######################################################################
            '''
            STEP - 2
              -- Space Amplification check after
                 deleting all the items
            '''
            self.log.debug("Step 2, Iteration= {}".format(count+1))
            _result = self.check_fragmentation_using_magma_stats(
                self.buckets[0],
                self.cluster.nodes_in_cluster)
            self.assertIs(_result, True,
                          msg_stats.format("magma"))

            _r = self.check_fragmentation_using_bucket_stats(
                self.buckets[0], self.cluster.nodes_in_cluster)
            self.assertIs(_r, True,
                          msg_stats.format("KV"))

            disk_usage = self.get_disk_usage(self.buckets[0],
                                             self.cluster.nodes_in_cluster)
            _res = disk_usage[0]
            self.log.info("Delete Iteration{}, Disk Usage= {}MB \
            ".format(count+1, _res))
            msg = "Disk Usage={}MB > {} * init_Usage={}MB"
            self.assertIs(_res > 0.5 * self.disk_usage[
                self.disk_usage.keys()[0]], False,
                msg.format(disk_usage[0], 0.5,
                           self.disk_usage[self.disk_usage.keys()[0]]))

            ######################################################################
            '''
            STEP - 3
              -- Recreate n items
            '''

            if count != self.test_itr - 1:
                self.log.debug("Step 2, Iteration= {}".format(count+1))
                self.doc_ops = "create"
                _ = self.loadgen_docs(self.retry_exceptions,
                                      self.ignore_exceptions,
                                      _sync=True)
                self.bucket_util._wait_for_stats_all_buckets()
                self.bucket_util.verify_stats_all_buckets(self.num_items)
            count += 1

            ######################################################################
        self.log.info("====test_basic_create_delete ends====")

    def test_parallel_creates_deletes(self):
        """
        Test Focus: Primary focus for this is to check space
                    Amplification.
                    Create new docs and deletes already created docs
                    Check disk_usage after each Iteration
        """
        self.log.info("====test_parallel_creates_deletes starts====")
        init_items = self.num_items

        self.create_end = self.num_items
        self.delete_end = self.num_items

        self.doc_ops = "create:delete"

        count = 0
        while count < self.test_itr:
            self.log.info("Iteration {}".format(count+1))
            if self.rev_write:
                self.create_start = -int(self.create_end + init_items - 1)
                self.create_end = -int(self.create_end - 1)
            else:
                self.create_start = self.create_end
                self.create_end += init_items

            if self.rev_del:
                self.delete_start = -int(self.delete_end + init_items - 1)
                self.delete_end = -int(self.delete_end - 1)
            else:
                self.delete_start = self.delete_end
                self.delete_end += init_items

            self.generate_docs(doc_ops="create")

            _ = self.loadgen_docs(self.retry_exceptions,
                                  self.ignore_exceptions,
                                  _sync=True)

            self.bucket_util._wait_for_stats_all_buckets()
            self.bucket_util.verify_stats_all_buckets(self.num_items)

            self.generate_docs(doc_ops="delete")

            if self.rev_write:
                self.create_end = -(self.create_start-1)
            if self.rev_del:
                self.delete_end = -(self.delete_start-1)

            # Space Amplification Check
            msg_stats = "{} stats fragmentation exceeds configured value"
            _result = self.check_fragmentation_using_magma_stats(
                self.buckets[0], self.cluster.nodes_in_cluster)
            self.assertIs(_result, True, msg_stats.format("magma"))

            _r = self.check_fragmentation_using_bucket_stats(
                self.buckets[0], self.cluster.nodes_in_cluster)
            self.assertIs(_r, True, msg_stats.format("KV"))

            disk_usage = self.get_disk_usage(
                self.buckets[0],
                self.cluster.nodes_in_cluster)
            if self.doc_size <= 32:
                msg = "Iteration={}, SeqTree={}MB exceeds keyTree={}MB"
                self.assertIs(
                    disk_usage[2] >= disk_usage[3], True,
                    msg.format(count+1, disk_usage[3], disk_usage[2]))
            else:
                msg = "Iteration={}, Disk Usage={}MB > {} * init_Usage={}MB"
                self.assertIs(disk_usage[0] > 2.5 * self.disk_usage[
                    self.disk_usage.keys()[0]],
                    False, msg.format(count+1, disk_usage[0], 2.5,
                                      self.disk_usage[self.disk_usage.keys()[0]]))
            #Space Amplifacation check Ends
            count += 1

        self.doc_ops = "delete"
        self.gen_delete = copy.deepcopy(self.gen_create)
        _ = self.loadgen_docs(self.retry_exceptions,
                              self.ignore_exceptions,
                              _sync=True)

        #Space Amplifaction check after all deletes
        _result = self.check_fragmentation_using_magma_stats(
            self.buckets[0], self.cluster.nodes_in_cluster)
        self.assertIs(_result, True, msg_stats.format("magma"))

        _r = self.check_fragmentation_using_bucket_stats(
            self.buckets[0], self.cluster.nodes_in_cluster)
        self.assertIs(_r, True, msg_stats.format("KV"))

        disk_usage = self.get_disk_usage(
                self.buckets[0],
                self.cluster.nodes_in_cluster)
        msg = "Disk Usage={}MB > {} * init_Usage={}MB"
        self.assertIs(disk_usage[0] > 0.4 * self.disk_usage[
            self.disk_usage.keys()[0]], False,
            msg.format(disk_usage[0], 0.4,
                       self.disk_usage[self.disk_usage.keys()[0]]))
        # Space Amplifiaction check ends

        self.change_swap_space(self.cluster.nodes_in_cluster,
                               disable=False)
        self.log.info("====test_parallel_create_delete ends====")
