#
# Copyright (c) 2016 Cisco and/or its affiliates, and
#                    Cable Television Laboratories, Inc. ("CableLabs")
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import unittest
import os
import zmq
import time
import socket
import subprocess
import signal
import rpd.provision.proto.process_agent_pb2 as pb2
from rpd.provision.process_agent.agent.agent import ProcessAgent
from rpd.provision.process_agent.l2tp.l2tp_agent import L2tpAgent
from rpd.l2tp.l2tpv3.testing.test_L2tpv3GcppSession import StaticL2tpProvision
from rpd.confdb.testing.test_rpd_redis_db import setup_test_redis, stop_test_redis
import rpd.gpb.StaticPwConfig_pb2 as StaticPwConfig_pb2
import rpd.l2tp.l2tpv3.src.L2tpv3GcppConnection as L2tpv3GcppSession


class TestL2tpAgent(unittest.TestCase):

    def setUp(self):
        # try to find the l2tp agent
        setup_test_redis()
        currentPath = os.path.dirname(os.path.realpath(__file__))
        dirs = currentPath.split("/")
        rpd_index = dirs.index("testing") - 2
        self.rootpath = "/".join(dirs[:rpd_index])
        self.pid = subprocess.Popen("coverage run --parallel-mode --rcfile=" + self.rootpath + "/.coverage.rc " +
                                    "/".join(dirs[:rpd_index]) +
                                    "/rpd/provision/process_agent/l2tp/l2tp_agent.py -s",
                                    executable='bash', shell=True)

    def tearDown(self):
        stop_test_redis()
        self.pid.send_signal(signal.SIGINT)
        self.pid.wait()
        self.pid = None
        self.stop_mastersim()
        os.system('rm -rf /tmp/ProcessAgent_AGENTTYPE_*')

    def start_mastersim(self):
        # try to find the l2tp agent
        self.mastersim_pid = subprocess.Popen("coverage run --parallel-mode --rcfile=" + self.rootpath +
                                              "/.coverage.rc " + self.rootpath +
                                              "/rpd/l2tp/l2tpv3/simulator/L2tpv3MasterSim.py ipv4",
                                              executable='bash',
                                              shell=True)

    def stop_mastersim(self):
        if getattr(self, 'mastersim_pid', None) is None:
            pass
        else:
            self.mastersim_pid.send_signal(signal.SIGINT)
            self.mastersim_pid.wait()
            self.mastersim_pid = None

    def test_l2tp_start_checkStatus_stop(self):
        context = zmq.Context()
        sock_push = context.socket(zmq.PUSH)
        sock_push.connect(ProcessAgent.SockPathMapping[ProcessAgent.AGENTTYPE_L2TP]['pull'])

        sock_api = context.socket(zmq.REQ)
        sock_api.connect(ProcessAgent.SockPathMapping[ProcessAgent.AGENTTYPE_L2TP]['api'])

        sock_pull = context.socket(zmq.PULL)
        sock_pull.bind("ipc:///tmp/test_l2tp_agent.sock")

        # test the successfully register
        event_request = pb2.api_request()
        reg = pb2.msg_manager_register()
        reg.id = "test_mgr"  # use a fake ccap id
        reg.action = pb2.msg_manager_register.REG
        reg.path_info = "ipc:///tmp/test_l2tp_agent.sock"
        event_request.mgr_reg.CopyFrom(reg)
        data = event_request.SerializeToString()

        sock_api.send(data)

        data = sock_api.recv()
        reg_rsp = pb2.api_rsp()
        reg_rsp.ParseFromString(data)
        print reg_rsp

        self.assertEqual(reg_rsp.reg_rsp.status, reg_rsp.reg_rsp.OK)

        # test the successfully register
        event_request = pb2.api_request()
        reg = pb2.msg_core_register()
        reg.mgr_id = "test_mgr"  # use a fake ccap id
        reg.ccap_core_id = "test_ccap_core"
        reg.action = pb2.msg_core_register.REG
        event_request.core_reg.CopyFrom(reg)
        data = event_request.SerializeToString()

        sock_api.send(data)

        data = sock_api.recv()
        reg_rsp = pb2.api_rsp()
        reg_rsp.ParseFromString(data)
        print reg_rsp

        self.assertEqual(reg_rsp.reg_rsp.status, reg_rsp.reg_rsp.OK)

        event_request = pb2.msg_event_request()
        event_request.action.id = "test_ccap_core"
        event_request.action.ccap_core_id = "test_ccap_core"
        event_request.action.event_id = ProcessAgent.AGENTTYPE_L2TP
        event_request.action.parameter = "lo;127.0.0.1"
        event_request.action.action = pb2.msg_event.START

        sock_push.send(event_request.SerializeToString())
        self.start_mastersim()
        # we want to receive 2 notifications, 1 for check status initial, 2 for the status update
        i = 2
        while i > 0:
            data = sock_pull.recv()
            rsp = pb2.msg_event_notification()
            rsp.ParseFromString(data)
            print rsp
            i -= 1
        # test stop
        event_request = pb2.msg_event_request()
        event_request.action.id = "test_ccap_core"
        event_request.action.event_id = ProcessAgent.AGENTTYPE_L2TP
        event_request.action.parameter = "lo;127.0.0.1"
        event_request.action.ccap_core_id = "test_ccap_core"
        event_request.action.action = pb2.msg_event.STOP
        sock_push.send(event_request.SerializeToString())

        data = sock_pull.recv()
        rsp = pb2.msg_event_notification()
        rsp.ParseFromString(data)
        print rsp

        # unregister the ccapcore
        event_request = pb2.api_request()
        reg = pb2.msg_core_register()
        reg.mgr_id = "test_mgr"  # use a fake ccap id
        reg.ccap_core_id = "test_ccap_core"
        reg.action = pb2.msg_core_register.UNREG
        event_request.core_reg.CopyFrom(reg)
        data = event_request.SerializeToString()

        sock_api.send(data)

        data = sock_api.recv()
        reg_rsp = pb2.api_rsp()
        reg_rsp.ParseFromString(data)
        print reg_rsp

        self.assertEqual(reg_rsp.reg_rsp.status, reg_rsp.reg_rsp.OK)

        # unregister the mgr
        event_request = pb2.api_request()
        reg = pb2.msg_manager_register()
        reg.id = "test_mgr"  # use a fake ccap id
        reg.action = pb2.msg_manager_register.UNREG
        reg.path_info = "ipc:///tmp/test_l2tp_agent.sock"
        event_request.mgr_reg.CopyFrom(reg)
        data = event_request.SerializeToString()

        sock_api.send(data)

        data = sock_api.recv()
        reg_rsp = pb2.api_rsp()
        reg_rsp.ParseFromString(data)
        print reg_rsp

        self.assertEqual(reg_rsp.reg_rsp.status, reg_rsp.reg_rsp.OK)

    def test_l2tp_arp_learn(self):
        staticPwCfg = StaticPwConfig_pb2.t_StaticPwConfig()
        self.fwdCfg = StaticL2tpProvision()
        self.fwdCfg.add_commStaticSession(staticPwCfg, 12, 0x80000001, 4,
                                          32768, True)
        self.fwdCfg.add_usStaticSession(staticPwCfg, 12, False)
        session1 = L2tpv3GcppSession.StaticL2tpSession(12)
        session1.updateRetstaticPseudowire(staticPwCfg)
        session1.updateComStaticPseudowire(staticPwCfg)
        session1.DestAddress = "127.0.0.1"
        session1.write()

        staticPwCfg = StaticPwConfig_pb2.t_StaticPwConfig()
        self.fwdCfg.add_commStaticSession(staticPwCfg, 12, 0x80000002, 5,
                                          32768, True)
        self.fwdCfg.add_usStaticSession(staticPwCfg, 12, False)
        session2 = L2tpv3GcppSession.StaticL2tpSession(12)
        session2.updateRetstaticPseudowire(staticPwCfg)
        session2.updateComStaticPseudowire(staticPwCfg)
        session2.DestAddress = "127.0.0.2"
        session2.write()

        try:
            os.system("reset arp")
            time.sleep(15)
            with open("/proc/net/arp") as f:
                arp_table = f.read()
                table = map(lambda x: x.split(), arp_table.split("\n"))
                self.assertTrue(table)
        except Exception as ex:
            print str(ex)
        session1.delete()
        session2.delete()


if __name__ == "__main__":
    unittest.main()
