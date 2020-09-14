#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
@author: kun
"""
__author__ = "kunxinz"
__email__ = "kunxinz@qq.com"

import configparser, json
import subprocess
import sys

import psutil
import xml.etree.cElementTree as et
# passwd
import bcrypt
from datetime import datetime
import threading
import docker
import os, shutil, traceback
import dill
import time
import socket
import paramiko
from Crypto.Cipher import AES
import GetCtanNameByPID as GCNBP
from collections import defaultdict
import nvidia_smi as nv
from pf_tm import PF_TM
# mail
from email.header import Header
from email.mime.text import MIMEText
from email.utils import parseaddr, formataddr
from kUtil import *
from labMaster import SRVM

pf_tm = PF_TM(False)

gcnmp = GCNBP.GetCtanNameByPID()  # class to get container name from process pid

class Kfs(object):
    def __init__(self, configXmlPath):
        self.configXml = configXmlPath

        # 执行文件路径
        self.overlayBin = './overlay2'
        self.sersyncBin = './sersync2'

        parser = et.parse(configXmlPath)
        self.parser = parser
        self.xfce_local = parser.getroot().find("xfce_local").get("str")
        self.low_local = parser.getroot().find("low_local").get("str")
        self.up_local = parser.getroot().find("up_local").get("str")
        self.work_local = parser.getroot().find("work_local").get("str")
        self.merge_local = parser.getroot().find("merge_local").get("str")

        self.low_mfs = parser.getroot().find("low_mfs").get("str")
        self.low_mfs_v = os.readlink(self.low_mfs)
        self.up_mfs = parser.getroot().find("up_mfs").get("str")
        self.up_mfs_v = os.readlink(self.up_mfs)

        # 版本控制
        self.newVer = int(parser.getroot().find('latestVersion').get('str'))
        self.keepVerNum = int(parser.getroot().find('versionNum').get('str'))

        # sersync 配置
        self.syncPid = ''
        self.rsyncLog = oj(os.path.dirname(self.configXml), 'rsync.log')  # 和config.xml同个文件夹
        self.sersync2Log = oj(os.path.dirname(self.configXml), 'sersync2.log')  # 和config.xml同个文件夹
        self.sersync2Pid = oj(os.path.dirname(self.configXml), 'sersync2.pid')
        self.syncTime = parser.getroot().find("syncTime").get("str")
        self.syncWatchPath = self.up_local
        self.parser.getroot().find('watch').set('str', self.syncWatchPath)  # 注册sersync的同步地址
        self.parser.getroot().find('syncLog').set('str', self.rsyncLog)
        self.parser.write(self.configXml)

    def mergeMfsDir(self):
        # after sync localUp
        parser = self.parser
        newVer = self.newVer
        keepVerNum = self.keepVerNum
        assert keepVerNum >= 2, 'keepVerNum < 2!'

        lowDirIdx = self.low_mfs_v.rfind('_')
        upDirIdx = self.up_mfs_v.rfind('_')

        # 版本以有up low为主,以论询方式进行管理
        newVer = (newVer + 1)%keepVerNum  # 最新版本+1轮换

        lowLatestDir = self.low_mfs_v[:lowDirIdx] + '_' + str(newVer)
        upLatestDir = self.up_mfs_v[:upDirIdx] + '_' + str(newVer)
        # 创建新版本的low_mfs_v和up_mfs_v
        os.system('mkdir {} {}'.format(lowLatestDir, upLatestDir))
        # 新版本可能存在，所以要清空
        os.system('sudo rm -rf {}/* {}/*'.format(lowLatestDir, upLatestDir))

        # 人工合并远程mfs
        merge_dir = lowLatestDir
        os.system('sudo {} {} {} {} {}'.format(self.overlayBin, self.up_local, merge_dir, self.up_mfs, self.low_mfs))
        # 将最新版本的low_mfs和up_mfs进行链接
        os.system('rm {} && ln -s {} {}'.format(self.low_mfs, lowLatestDir, self.low_mfs))
        os.system('rm {} && ln -s {} {}'.format(self.up_mfs, upLatestDir, self.up_mfs))

        parser.getroot().find('latestVersion').set('str', str(newVer))
        parser.write(self.configXml)

    def umount(self):
        os.system("sudo umount {}".format(self.merge_local))  # 解挂载本地merge

    def sersyncStart(self, forceStart=False, allSync=False):
        # 先检查sersync是否存活
        if self.sersyncIsAlive():
            if not forceStart:
                return True
            else:
                self.sersyncStop()  # 先关闭原有的，再开启新的

        # print('''
        # 		option -t: set automatic sync time
        # 		option -l: set the directory to be sync
        # 		option -d: run as daemon
        # 		option -r: rsync all the local files to the remote servers before the sersync work
        # 		option -o: config xml name
        # 		option -m: working plugin name
        # 		option -n: thread num
        # 		option -x: default args
        # 		option -w: watch dir
        # 		e.g.: sersync2 -t 30 -l /home/duke/Desktop/test2 -l /home/duke/Desktop/test3
        # 		''')
        watchPath = self.parser.getroot().find('watch').get('str')  # 检查watchPath是否非空
        assert watchPath != '', 'sync watch path is Null'
        if allSync:
            cmd = 'sudo {} -r -t {} -g {} -w {} -l {} > {} 2>&1'.format(
                self.sersyncBin, self.syncTime, self.rsyncLog, watchPath, self.up_mfs, self.sersync2Log)
        else:
            cmd = 'sudo {} -t {} -g {} -w {} -l {} > {} 2>&1'.format(
                 self.sersyncBin, self.syncTime, self.rsyncLog, watchPath, self.up_mfs, self.sersync2Log)
        os.system(cmd)
        print('sersync start')
        time.sleep(1)
        with open(self.sersync2Log, 'r') as f:
            for line in f.readlines():
                if 'pid' in line:  # 'pid: 3579179'
                    self.syncPid = line.split(':')[1].strip()
                    break
        self.parser.getroot().find('syncPid').set('str', self.syncPid)
        self.parser.write(self.configXml)
        return True

    def sersyncChk(self):
        if not oe(self.rsyncLog):
            return True  # 如果不存在该文件，说明rsync根本还没有工作
        with open(self.rsyncLog, 'r') as f:
            lines = f.readlines()
        if len(lines) > 0:
            endLine = lines[-1]
            return 'sent' in endLine
        else:
            return True

    def sersyncFlush(self):
        pass

    def sersyncIsAlive(self):
        pid = self.parser.getroot().find('syncPid').get('str')
        return pid in ls('/proc')

    def sersyncStop(self):
        pid = self.parser.getroot().find('syncPid').get('str')
        if self.sersyncIsAlive():
            os.system('sudo kill -9 {}'.format(pid))
            self.parser.getroot().find('syncPid').set('str', '')
            self.parser.write(self.configXml)

    def cleanUpLocal(self):
        os.system('sudo rm -rf {}/* {}/*'.format(self.work_local, self.up_local))  # 删除work和up文件夹

    def cleanAllExHome(self, cleanHome=False):  # 清除low_local和up_local中的所有文件夹,还有mfs，除了home
        if not cleanHome:
            cmd = 'sudo find {}/* -maxdepth 0 | grep -v {} | xargs sudo rm -rf'.format(self.low_local, 'home')
            os.system(cmd)
            cmd = 'sudo find {}/* -maxdepth 0 | grep -v {} | xargs sudo rm -rf'.format(self.up_local, 'home')
            os.system(cmd)
        else:
            os.system('sudo rm -rf {}/*'.format(self.low_local))
            os.system('sudo rm -rf {}/*'.format(self.up_local))

        os.system('sudo rm -rf {}/*'.format(self.work_local))
        os.system('rm {} {} {}'.format(self.sersync2Log, self.rsyncLog, self.configXml))
        low_mfs_v = os.readlink(self.low_mfs)  # 得到最新版本的low_mfs_v
        mfs_dir = os.path.dirname(low_mfs_v)
        # 删除除low_mfs_v之外的所有文件
        cmd = 'sudo find {}/* -maxdepth 0 | grep -v {} | xargs sudo rm -rf'.format(mfs_dir, low_mfs_v)
        os.system(cmd)
        if not oe(oj(mfs_dir, 'low_mfs_0')):
            os.system('mv {} {}'.format(low_mfs_v, oj(mfs_dir, 'low_mfs_0')))  # 改为 low_mfs_0

    def mount(self):
        # 先判断是否已挂载，再挂载
        if 'xfce_local_flag' in ls(self.merge_local):
            return # 该文件存在则表示已挂载
        cmd = 'sudo mount -t overlay overlay -o suid,lowerdir={}:{},upperdir={},workdir={}, {}'.format(
            self.low_local, self.xfce_local, self.up_local, self.work_local, self.merge_local)
        os.system(cmd)

class labNode(object):
    def __init__(self, confPath=None):
        # dir path
        fileDir = os.path.dirname(__file__)  # 当前文件夹

        # 配置参数默认文件
        if confPath is None:
            confPath = oj(fileDir, 'bkConfxml.xml')
        self.configXmlBk = confPath
        parser = et.parse(self.configXmlBk)
        self.parser = parser
        pRoot = parser.getroot()

        # 结点名字
        self.client = pRoot.find('machine_name').get('str')
        self.connectedFlag = False

        # 服务器参数
        self.srvAddr = pRoot.find('srv_master_addr').get('str')
        self.srvPort = int(pRoot.find('srv_master_port').get('str'))
        self.srvAddrPort = (self.srvAddr, self.srvPort)
        self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.echoArgs_dt_client = {'srv':None}
        self.echoArgsFlag_dt_client = {'srv':False}
        self.srvSyncFlagFinish = False
        self.clientRun()
        if not self.connectedFlag: return

        # mfs_dir 和 xfce_local 必须事先存在
        tmp = pRoot.find('mfs_dir').get('str')
        self.mfs_dir = oj(fileDir, 'mfs_dir') if tmp == "" else tmp
        tmp = pRoot.find('xfce_local').get('str')
        self.xfce_local = oj(fileDir, 'xfce_local') if tmp == "" else tmp
        assert oe(self.mfs_dir) and oe(self.xfce_local), 'mfs dir 或 xfce_local 不存在'

        # get the containers
        self.apiClient = docker.APIClient()
        self.containers = docker.from_env().containers
        self.imgs = docker.from_env().images

        # kfs 参数文件
        self.kfs_dt_user = {}

        # conf user public 可以不事先存在
        tmp = pRoot.find('docker_conf_dir').get('str')
        self.docker_conf_dir = oj(fileDir, 'docker_conf_dir') if tmp == "" else tmp  # 如果缺省则配置为当前文件夹
        tmp = pRoot.find('docker_user_dir').get('str')
        self.docker_user_dir = oj(fileDir, 'docker_user_dir') if tmp == "" else tmp
        tmp = pRoot.find('docker_public_dir').get('str')
        self.docker_public_dir = oj(fileDir, 'docker_public_dir') if tmp == "" else tmp
        os.makedirs(self.docker_conf_dir, exist_ok=True)
        os.makedirs(self.docker_user_dir, exist_ok=True)
        os.makedirs(self.docker_public_dir, exist_ok=True)

        # img name
        self.dfImg = pRoot.find('img_name').get('str')
        assert len(self.imgs.list(self.dfImg)) != 0, '{} 镜像不存在'.format(self.dfImg)

        # 内存百分比和绝对值限制
        self.dfMemPcnt = float(pRoot.find('mem_limit_pcnt').get('str'))
        self.dfMemAbs = pRoot.find('mem_limit_abs').get('str')
        assert 0 < self.dfMemPcnt <= 1, 'mem_limit_pcnt value error'

        # 共享内存百分比和绝对值限制
        self.dfShmPcnt = float(pRoot.find('shm_limit_pcnt').get('str'))
        self.dfShmAbs = pRoot.find('shm_limit_abs').get('str')
        assert 0 < self.dfShmPcnt <= 1, 'shm_pcnt value error'

        # cpu主机保留核心数
        self.dfCpuRestCoreNum = int(pRoot.find('cpu_rest_core_num').get('str'))

        # port args
        self.initPortHead = int(pRoot.find('docker_port_base').get('str'))
        self.portNum = int(pRoot.find('docker_user_port_num').get('str'))

        # get the data dict
        self.dataPath = oj(self.docker_conf_dir, 'data_dt')

        # data
        self.saveData_dt = {}
        self.dataDt_dt_userName = {}
        self.portHeadUsed_ls = []
        self.portHeadUsable_ls = []
        self.mail_dt_user = {}
        self.starTime_dt_user = {}

        self.idxHportLs_dt_client = 0
        self.idxPW = 1
        self.idxMail = 2
        self.idxStarTime = 3
        self.idxRemark = 4
        self.idxPhone = 5

        # cpu 统计变量
        self.userStatsRtream = {}
        self.preCpuStats = defaultdict(lambda : [None, None])

        # mail flag
        self.mailSendFlag_ls = []
        self.mailWarnHour = int(pRoot.find('time_send_mail').get('str'))
        self.mailDeadHour = int(pRoot.find('time_stop_ctan').get('str'))

        # 请求服务器同步数据
        self.plsSync()

        # 自检
        self.checkPass = True
        self.checkErrPort = []
        self.initCheck()

        # nvidia
        nv.nvmlInit()
        self.resInfo = {}
        self.gpuInfo = self.__get_gpu_info()

        # check the container running time
        self.checkTimePeriod = 60
        self.chkCtanTimer = threading.Timer(self.checkTimePeriod, self.chkLivingTimerFun)
        self.chkCtanTimer.setDaemon(True)
        self.chkCtanTimer.start()

        self.updateStatusPeriod = 2
        self.chkStatsTimer = threading.Timer(self.updateStatusPeriod, self.chkStatsTimerFun)
        self.chkStatsTimer.setDaemon(True)
        self.chkStatsTimer.start()

    def clientRun(self, tryNum=300):
        i = 0
        while i < tryNum:
            i += 1
            if not self.connectedFlag:
                try:
                    print('-----未连接服务器，尝试第{}次连接-----'.format(i))
                    self.sk.connect(self.srvAddrPort)
                    self.connectedFlag = True
                    threading.Thread(target=self.clientRecvHandler).start()  # 开启接收线程来处理
                    print('----第{}次连接服务器成功----'.format(i))
                    return True
                except:
                    print('-----第{}次连接服务器失败-----'.format(i))
                    self.connectedFlag = False
            else:
                i = 0
            time.sleep(10)
        print('尝试连接服务器{}次均失败'.format(tryNum))
        return False

    def _clientRecvHandler(self, cmd_byte):
        cmd_ls = dill.loads(cmd_byte)
        _, userName, action, args = cmd_ls
        print('从服务器接收的的命令：{}'.format(cmd_ls))
        if action == SRVM.ACTION_START:
            self.start(userName)
            self.doAction(userName, SRVM.ACTION_ECHO, 'success')
        elif action == SRVM.ACTION_STOP:
            self.stop(userName)
            self.doAction(userName, SRVM.ACTION_ECHO, 'success')
        elif action == SRVM.ACTION_REMOVE:
            self.remove(userName)
            self.doAction(userName, SRVM.ACTION_ECHO, 'success')
        elif action == SRVM.ACTION_SOLID:
            self.solid(userName)
            self.doAction(userName, SRVM.ACTION_ECHO, 'success')
        elif action == SRVM.ACTION_CREATEUSER:
            self.createUser(userName, **args)
            self.doAction(userName, SRVM.ACTION_ECHO, 'success')
        elif action == SRVM.ACTION_SYNC:
            dataDt_dt_userName = args
            self.syncData(dataDt_dt_userName)
        elif action == SRVM.ACTION_ECHO:
            self.echoArgs_dt_client['srv'] = args
            self.echoArgsFlag_dt_client['srv'] = True  # 表示已接收到返回信息
        elif action == SRVM.ACTION_GETBASEINFO:
            res = self.getCtansBaseInfoDt()
            self.doAction('all', SRVM.ACTION_ECHO, args=res)
        elif action == SRVM.ACTION_GETGPUINFO:  # gpu info
            res = self.getGPUInfo()
            self.doAction('all', SRVM.ACTION_ECHO, args=res)
        elif action == SRVM.ACTION_GETCTANINFO:  # ctan info
            res = self.getCtanInfo(userName)
            self.doAction('all', SRVM.ACTION_ECHO, args=res)
        elif action == SRVM.ACTION_GETCNAMEBYPID:  # ctan name by pid
            res = self.getCtanNameByPid(int(args))
            self.doAction('all', SRVM.ACTION_ECHO, args=res)

    def clientRecvHandler(self):  # 该函数处理 接收来的信息
        while True:  # 接收循环
            cmd_byte = self.sk.recv(2048)
            if cmd_byte == b'':
                print('服务器链接断开')
                break
            threading.Thread(target=self._clientRecvHandler, args=(cmd_byte,)).start()
        self.connectedFlag = False
        self.sk.close()  # 关闭，重启
        self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.clientRun()  # 尝试再连接，如果还是失败则直接退出

    def doAction(self, userName, action, args=None):
        if args is None: args = 'None'
        cmdLs = ['srv', userName, action, args]
        if not action == SRVM.ACTION_ECHO: # echo 本身不用设置flag
            self.echoArgsFlag_dt_client['srv'] = False
        self.sk.sendall(dill.dumps(cmdLs))

    def getEchoData(self):
        while True:
            time.sleep(0.5)
            if self.echoArgsFlag_dt_client['srv']:
                self.echoArgsFlag_dt_client['srv'] = False  # 读取后设置为False
                return self.echoArgs_dt_client['srv']

    def clientSend(self, cmdLs):
        self.echoArgsFlag_dt_client = False  # 主动发要设置为False
        self.sk.sendall(dill.dumps(cmdLs))

    def plsSync(self):
        # 请求服务器返回存储数据
        cmd_ls = ['srv', 'all', SRVM.ACTION_PLSSYNC, 'None']
        self.srvSyncFlagFinish = False
        self.clientSend(cmd_ls)
        while not self.srvSyncFlagFinish:
            time.sleep(0.5)  # 等待同步完成

    def plsSave(self):
        # 请求服务器存储数据
        # args = dill.dumps(self.dataDt_dt_userName)
        cmd_ls = ['srv', 'all', SRVM.ACTION_PLSSAVE, self.dataDt_dt_userName]
        self.srvSyncFlagFinish = False
        self.clientSend(cmd_ls)
        while not self.srvSyncFlagFinish:
            time.sleep(0.5)  # 等待同步完成

    def syncData(self, dataDt_dt_userName):
        # 加载从服务器发送过来的数据
        self.dataDt_dt_userName = dataDt_dt_userName
        self.portHeadUsed_ls = [int(v[self.idxHportLs_dt_client][self.client][0]) for v in self.dataDt_dt_userName.values()]
        self.portHeadUsed_ls.sort()
        self.mail_dt_user = {u: dataDt[self.idxMail] for u, dataDt in self.dataDt_dt_userName.items()}
        self.starTime_dt_user = {u: dataDt[self.idxStarTime] for u, dataDt in self.dataDt_dt_userName.items()}
        self.srvSyncFlagFinish = True

    def initCheck(self):
        def getCtanPortHead(userName, port, proto='tcp'):
            rawInfo = self.apiClient.inspect_container(userName)
            return rawInfo['HostConfig']['PortBindings'][str(port) + '/' + proto][0]['HostPort']

        for user, dataDt in self.dataDt_dt_userName.items():
            port = dataDt[self.idxHportLs_dt_client][self.client][0]
            try:
                self.containers.get(user)  # whether the containers exist
            except:
                self.checkPass = False
                print('There is no such container: {}'.format(user))
                self.checkErrPort.append(str(port))

            try:
                assert str(port) == str(getCtanPortHead(user, 22))  # whether the port is right
            except:
                self.checkPass = False
                print('There have a bad container port: {0}: {1}'.format(user, port))
                self.checkErrPort.append(str(port))

    @staticmethod
    def getCtanNameByPid(pid):  # 根据pid来查找容器名
        try:
            ctanName = gcnmp.getCtanNameByPid(pid)
        except Exception:
            ctanName = None
        if ctanName is None:
            ctanName = 'server'
        return ctanName

    def getCtanUpTime(self, userName):
        starTime_stamp = self.starTime_dt_user[userName]
        nowtime_stamp = time.time()
        sec_int = int(nowtime_stamp - starTime_stamp)
        all_m, s = divmod(sec_int, 60)
        h, m = divmod(all_m, 60)
        str_uptime = '{:d}:{:0>2d}:{:0>2d}'.format(h, m, s)
        return str_uptime, h, m, s

    # 获取所有容器静态信息
    def getCtansBaseInfoDt(self):
        def getCtanIp(ctanName):
            rawInfo = self.apiClient.inspect_container(ctanName)
            return rawInfo['NetworkSettings']['IPAddress']

        res = {}
        userName = ''
        try:
            for userName, dataDt in self.dataDt_dt_userName.items():
                # [userName, 'Amax:29000~29009', 'RUNNING', ip, uptime, remark]
                # [userName, 'Amax:29000~29009', 'STOPED', 'NONE', '00:00:00', remark]
                res[userName] = []
                res[userName].append(userName)
                hPort_ls = dataDt[self.idxHportLs_dt_client][self.client]
                hPortHead, hPortEnd = hPort_ls[0], hPort_ls[-1]
                res[userName].append('{}:{}~{}'.format(self.client, hPortHead, hPortEnd))
                if self.containers.get(userName).status == "running":
                    res[userName].append("RUNNING")
                    IP = getCtanIp(userName)
                    res[userName].append(IP)
                    duration_str = (self.getCtanUpTime(userName))[0]
                    res[userName].append(duration_str)
                else:
                    res[userName].append("STOPED")
                    res[userName].append("NONE")
                    res[userName].append("00:00:00")
                remark = dataDt[self.idxRemark]
                res[userName].append(remark)
        except KeyError:
            print("[Manager]: Data file error with " + userName)
        return res

    # 获取开机和关机容器列表
    def getRuningUsername(self):
        userName_ls = []
        for userName in self.dataDt_dt_userName:
            if self.containers.get(userName).status == 'running':
                userName_ls.append(userName)
        return userName_ls

    # 生成新端口
    def generateNewPortHead(self):
        def isIdle(port, ctnu=1):
            idleFlag = True
            for i in range(ctnu):
                sTCP = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sUDP = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sTCP.bind(('', int(port) + i))
                    sTCP.listen(1)
                    sUDP.bind(('', int(port) + i))
                except:
                    traceback.print_exc()
                    idleFlag = False
                finally:
                    sTCP.close()
                    sUDP.close()
                    if not idleFlag:  # 如果非空闲，有个被占用了，那么剩下的不用判断了，直接是非空闲
                        break
            return idleFlag

        # 如果是刚创建，那么初始化，添加初始端口
        if not self.portHeadUsed_ls and not self.portHeadUsable_ls:
            self.portHeadUsable_ls.append(self.initPortHead)
        # 先搜索现有可用的端口
        for portHead in self.portHeadUsable_ls:
            if isIdle(portHead, self.portNum):
                self.portHeadUsable_ls.remove(portHead)  # 移出可用列表
                return int(portHead)
        # 如果没有，则取最大的端口加偏移
        portHead = max(self.portHeadUsed_ls) + self.portNum
        while not isIdle(portHead, self.portNum):
            portHead += self.portNum
        return int(portHead)

    def createUserDir(self, userName):
        # 创建本地文件夹
        low_local = oj(self.docker_user_dir, userName, 'low_local')
        up_local = oj(self.docker_user_dir, userName, 'up_local')
        work_local = oj(self.docker_user_dir, userName, 'work_local')
        merge_local = oj(self.docker_user_dir, userName, 'merge_local')
        os.system('mkdir -p {} {} {} {}'.format(low_local, up_local, work_local, merge_local))

        # 创建mfs文件夹
        low_mfs = oj(self.mfs_dir, userName, 'low_mfs')
        up_mfs = oj(self.mfs_dir, userName, 'up_mfs')
        os.system('mkdir -p {}_0 {}_0'.format(low_mfs, up_mfs))
        # 创建low_mfs_0文件夹，然后再链接到low_mfs
        os.system('rm -rf {} {}'.format(low_mfs, up_mfs))  # 先保证没有文件夹，不然会链接到内部
        os.system('ln -s {}_0 {}'.format(low_mfs, low_mfs))
        os.system('ln -s {}_0 {}'.format(up_mfs, up_mfs))

        # 链接low_mfs文件夹到low_local文件夹
        os.system('rm -rf {}'.format(low_local))  # 先删除本地low的软链接
        os.system('ln -s {} {}'.format(low_mfs, low_local))  # 把最新的mfsLow进行链接
        return low_local, up_local, work_local, merge_local, low_mfs, up_mfs

    def createUser(self, userName, passwd='123456', mail='Null', remark='Null', phone='0'):
        try:
            # 检查名字是否重合和密码是否小于6位
            assert userName not in self.dataDt_dt_userName, 'user name already exist'
            assert len(passwd) >= 6, 'passwd len is smaller than 6'

            # 创建对应的文件夹和xml文件
            low_local, up_local, work_local, merge_local, low_mfs, up_mfs = self.createUserDir(userName)

            # 和xfce_local合并
            cmd = 'sudo mount -t overlay overlay -o suid,lowerdir={}:{},upperdir={},workdir={}, {}'.format(
                low_local, self.xfce_local, up_local, work_local, merge_local)
            os.system(cmd)

            # 获得镜像
            img = self.dfImg
            # 获得端口映射
            port_base = self.generateNewPortHead()
            hPort_ls = list(range(port_base, port_base + self.portNum))
            cPort_ls = [22, 5901] + list(range(8080, 8080 + self.portNum - 2))  # ssh vnc 8080 8081 ... 8087
            hPortLs_dt_cPortLs = dict(zip(cPort_ls, hPort_ls))

            # generate the volume map
            hostPublicDir = self.docker_public_dir
            ctanPublicDir = '/PUBLIC_dir'

            hostUserRootfs = merge_local
            # 清除原先的目录
            # if os.path.exists(hostUserRootfs):
            #     shutil.rmtree(hostUserRootfs)
            ctanUserRootfs = '/'
            rootDir_ls = 'bin boot etc home lib lib64 opt root sbin srv usr var'.split(' ')
            userVolMap = {}
            for rootDir in rootDir_ls:
                hostPath = oj(hostUserRootfs, rootDir)
                ctanPath = oj(ctanUserRootfs, rootDir)
                userVolMap[hostPath] = {'bind': ctanPath, 'mode': 'rw'}
            hostUserHome = oj(hostUserRootfs, 'home', userName)

            os.makedirs(hostUserHome, exist_ok=True)
            os.makedirs(hostPublicDir, exist_ok=True)
            publicMount = docker.types.Mount(target=ctanPublicDir,  # 这里使用高级的挂载方式，实现public内部的递归挂载
                                              source=hostPublicDir,
                                              type='bind',
                                              read_only=True,
                                              propagation='rslave'
                                              )


            totalMem = psutil.virtual_memory().total
            limitMem = '{:d}g'.format(int(totalMem * float(self.dfMemPcnt) / 1024 / 1024 / 1024))
            limitShMem = '{:d}g'.format(int(totalMem * float(self.dfShmPcnt) / 1024 / 1024 / 1024))
            if self.dfMemAbs != '': limitMem = self.dfMemAbs
            if self.dfShmAbs != '': limitShMem = self.dfShmAbs

            if self.dfCpuRestCoreNum >= psutil.cpu_count():
                print('warning, cpu reset core is larger than real count')
                cpuset_cpus = '0-{:d}'.format(psutil.cpu_count() - 1)
            else:
                cpuset_cpus = '0-{:d}'.format(psutil.cpu_count() - 1 - self.dfCpuRestCoreNum)

            # 生成容器
            self.containers.run(img,
                                # 命令
                                command='/root/heart.sh',  # 启动脚本
                                # 后台
                                detach=True,
                                # 主机名字
                                hostname=userName + 'VM',
                                # 容器名字
                                name=userName,
                                # 工作目录
                                working_dir=oj('/home', userName),
                                # 端口
                                ports=hPortLs_dt_cPortLs,
                                # 内存限制
                                mem_limit=limitMem,
                                memswap_limit=limitMem,
                                # 精细化特权,允许加载网络端口和重启
                                cap_add=['NET_ADMIN'],
                                # 允许使用的CPU范围，最后一个保留
                                cpuset_cpus=cpuset_cpus,
                                # 共享内存大小
                                shm_size=limitShMem,
                                # 挂载卷
                                volumes=userVolMap,
                                # more detail mount
                                mounts=[publicMount],
                                # 运行环境
                                runtime='nvidia',
                                dns=['114.114.114.114'],
                                # NVIDIA 环境变量
                                environment=["NVIDIA_DRIVER_CAPABILITIES=all",
                                             'LANG=zh_CN.UTF-8',
                                             'LC_ALL=zh_CN.UTF-8',
                                             'NVIDIA_VISIBLE_DEVICES=all'],  # 此变量让nvidia环境起作用
                                # 超级权限
                                # privileged = True , \
                                )

            time.sleep(1)

            ctan = self.containers.get(userName)
            # 复制初始化文件到用户home文件夹下
            os.system('cp -r {0} {1}'.format(self.docker_conf_dir, hostUserHome))
            # 生成初始化脚本
            ctanCreateUserShPath = oj('/home', userName, os.path.basename(self.docker_conf_dir), 'createUser.sh')
            initCmd = "/bin/bash -c \"echo '{} {}' | {} \"".format(userName, passwd, ctanCreateUserShPath)  # 以root身份执行
            # 执行初始化脚本
            ctan.exec_run(initCmd)
            ctan.exec_run('/bin/bash /etc/rc.local')  # 执行rc.local
            # remove the conf dir
            shutil.rmtree( oj(hostUserHome, os.path.basename(self.docker_conf_dir)) )

            # 成功后更新存储表
            starTime = int(time.time())

            hashPw = bcrypt.hashpw(passwd.encode('utf_8'), bcrypt.gensalt(10))

            #     生成xml文件
            userConfXmlPath = oj(self.docker_user_dir, userName, '{}_config.xml'.format(userName))
            os.system('cp {} {}'.format(self.configXmlBk, userConfXmlPath))
            parser = et.parse(userConfXmlPath)
            pRoot = parser.getroot()
            pRoot.find('low_local').set('str', low_local)
            pRoot.find('up_local').set('str', up_local)
            pRoot.find('work_local').set('str', work_local)
            pRoot.find('merge_local').set('str', merge_local)
            pRoot.find('low_mfs').set('str', low_mfs)
            pRoot.find('up_mfs').set('str', up_mfs)

            # 保存数据
            hPortLs_dt_client = {}
            if userName in self.dataDt_dt_userName:
                # 如果原先在其他机器创建了，那么端口列表不能覆盖，而是添加
                hPortLs_dt_client = self.dataDt_dt_userName[userName][self.idxHportLs_dt_client]
            hPortLs_dt_client.update({self.client: hPort_ls})
            self.dataDt_dt_userName[userName] = {
                 # 基本docker信息，可直接覆盖
                 self.idxPW: hashPw,
                 self.idxMail: mail,
                 self.idxStarTime: starTime,
                 self.idxRemark: remark,
                 self.idxPhone: phone,
                 # 端口列表，在上文已做处理
                 self.idxHportLs_dt_client: hPortLs_dt_client,
             }

            parser.write(userConfXmlPath)  # 开始同步
            self.plsSave()

            # 开始sersync
            self.sersyncStart(userName, allSync=True)
            return True
        except Exception as e:
            traceback.print_exc()
            if not e.args == 'user name already exist' and \
                    len(self.containers.list(filters={'name':userName})) != 0:
                self.containers.get(userName).remove(force=True)  # 说明刚才创建成功
            if 'merge_local' in locals():
                # 失败了要解挂载
                os.system('sudo umount {}'.format(merge_local))
                # 清空work和up
                os.system('sudo rm -rf {}/* {}/*'.format(work_local, up_local))
            return False

    def getKfs(self, userName):
        configXml = oj(self.docker_user_dir, userName, '{}_config.xml'.format(userName))
        if userName in self.kfs_dt_user:
            kfs = self.kfs_dt_user[userName]
        else:
            kfs = Kfs(configXml)
            self.kfs_dt_user[userName] = kfs
        return kfs

    def mount(self, userName):
        kfs = self.getKfs(userName)
        kfs.mount()

    def umount(self, userName):
        kfs = self.getKfs(userName)
        kfs.umount()

    def sersyncStart(self, userName, allSync=False):
        kfs = self.getKfs(userName)
        kfs.sersyncStart(allSync=allSync)

    def sersyncStop(self, userName):
        kfs = self.getKfs(userName)
        kfs.sersyncStop()

    def sersyncChk(self, userName):
        kfs = self.getKfs(userName)
        return kfs.sersyncChk()

    def sersyncFlush(self, userName):
        kfs = self.getKfs(userName)
        return kfs.sersyncFlush()

    def mergeMfs(self, userName):
        kfs = self.getKfs(userName)
        kfs.mergeMfsDir()

    def cleanAllExHome(self, userName, cleanHome=False):
        kfs = self.getKfs(userName)
        kfs.cleanAllExHome(cleanHome)

    def cleanUpLocal(self, userName):
        kfs = self.getKfs(userName)
        kfs.cleanUpLocal()

    def start(self, userName):
        try:
            ctan = self.containers.get(userName)
            self.dataDt_dt_userName[userName][self.idxStarTime] = int(datetime.now().timestamp())  # 写入启动时间
            self.plsSave()   # 需要在启动前写入文件，否则容易启动中时数据还没有更新完毕导致时间错误
            self.mount(userName)
            self.sersyncStart(userName)
            ctan.start()
            ctan.exec_run('/bin/bash /etc/rc.local')
        except Exception:
            traceback.print_exc()
            return False
        return True

    def stop(self, userName):
        try:
            if userName in self.getRuningUsername():
                ctan = self.containers.get(userName)
                ctan.exec_run('/bin/bash /etc/rc.preShutdown')
                ctan.stop()
                self.sersyncFlush(userName)
                while not self.sersyncChk(userName):
                    time.sleep(0.5)  # 等待同步完成
                self.sersyncStop(userName)
        except Exception:
            traceback.print_exc()
            return False
        return True

    def remove(self, userName, cleanHome=True):
        try:
            ctan = self.containers.get(userName)
            ctan.stop()
            self.sersyncStop(userName)
            ctan.remove()
            self.umount(userName)
            self.cleanAllExHome(userName, cleanHome=cleanHome)
            rmPortHead = self.dataDt_dt_userName[userName][self.idxHportLs_dt_client][self.client][0]
            self.portHeadUsed_ls.remove(rmPortHead)  # 清除头端口
            self.portHeadUsable_ls.append(rmPortHead)  # 加入到可用列表
            self.dataDt_dt_userName.pop(userName)  # 清除用户
            self.plsSave()
        except:
            traceback.print_exc()
            return False
        return True

    def solid(self, userName):
        if userName in self.getRuningUsername():
            ctan = self.containers.get(userName)
            ctan.exec_run('/bin/bash /etc/rc.preShutdown')
            ctan.stop()
            self.sersyncFlush(userName)
            while not self.sersyncChk(userName):
                time.sleep(0.5)
            self.sersyncStop(userName)

        self.umount(userName)
        self.mergeMfs(userName)
        self.cleanUpLocal(userName)

    def sendMail(self, mail_addr):
        mail_subject = '服务器倒计时关闭通知'
        mail_txt = '你好，服务器还有12小时即将关闭，如果需要继续工作，请前往服务器主界面重置计时器'
        # def _format_addr(s):
        #     name, addr = parseaddr(s)
        #     return formataddr((Header(name, 'utf-8').encode(), addr))
        # from_addr = 'a207_srv@163.com'
        # password = 'server010203'
        # to_addr = mail_addr
        # smtp_server = 'smtp.163.com'
        # msg = MIMEText(mail_txt, 'plain', 'utf-8')
        # msg['From'] = _format_addr('Python爱好者 <%s>' % from_addr)
        # msg['To'] = _format_addr('管理员 <%s>' % to_addr)
        # msg['Subject'] = Header(mail_subject, 'utf-8').encode()
        #
        # server = smtplib.SMTP(smtp_server, 25)
        # # server.set_debuglevel(1)
        # server.login(from_addr, password)
        # server.sendmail(from_addr, [to_addr], msg.as_string())
        # server.quit()
        cmd = 'echo {} | mail -s {} {}'.format(mail_txt, mail_subject, mail_addr)
        os.system(cmd)

    # 对容器运行时间检查
    def chkLivingTimerFun(self):
        try:
            runningUserName_ls = self.getRuningUsername()
            for runningUserName in runningUserName_ls:
                upTime = self.getCtanUpTime(runningUserName)
                upHour = upTime[1]
                if self.mailWarnHour < upHour < self.mailDeadHour:
                    mailAddr = self.mail_dt_user[runningUserName]
                    if mailAddr is not None and runningUserName not in self.mailSendFlag_ls:
                        # print('send mail {}'.format(mailAddr))
                        self.sendMail(mailAddr)
                        self.mailSendFlag_ls.append(runningUserName)
                elif self.mailDeadHour <= upHour:
                    print('stop {}'.format(runningUserName))
                    # 这里有可能直接一启动就已经超时，所以需要处理
                    if runningUserName in self.mailSendFlag_ls:
                        self.mailSendFlag_ls.remove(runningUserName)
                    self.stop(runningUserName)
        except:
            traceback.print_exc()
        self.chkCtanTimer = threading.Timer(self.checkTimePeriod, self.chkLivingTimerFun)
        self.chkCtanTimer.setDaemon(True)
        self.chkCtanTimer.start()

    # 更新容器资源
    def chkStatsTimerFun(self):
        try:
            for userName in self.getRuningUsername():
                self.resInfo[userName] = self.__get_ctan_verbose_stats(userName)
        except Exception:
            print('获取容器信息错误')
            traceback.print_exc()
        try:
            self.gpuInfo = self.__get_gpu_info()
        except:
            print('获取GPU信息错误')
            traceback.print_exc()
        self.chkStatsTimer = threading.Timer(self.updateStatusPeriod, self.chkStatsTimerFun)
        self.chkStatsTimer.setDaemon(True)
        self.chkStatsTimer.start()

    def getCtanInfo(self, name):
        if name in self.resInfo:
            return self.resInfo[name]
        else:
            return None

    def getGPUInfo(self):
        return self.gpuInfo

    def __get_ctan_verbose_stats(self, userName):
        # 连续获得参数
        def graceful_chain_get(d, *args, default=None):
            t = d
            for a in args:
                try:
                    t = t[a]
                except (KeyError, ValueError, TypeError, AttributeError):
                    return default
            return t

        # 计算cpu使用占比
        def calculate_cpu_percent2(d, previous_cpu_total=None, previous_cpu_system=None):
            cpu_percent = 0.0
            cpu_total = float(d["cpu_stats"]["cpu_usage"]["total_usage"])
            if previous_cpu_total is None:
                previous_cpu_total = cpu_total
            cpu_delta = cpu_total - previous_cpu_total
            cpu_system = float(d["cpu_stats"]["system_cpu_usage"])
            if previous_cpu_system is None:
                previous_cpu_system = cpu_system
            system_delta = cpu_system - previous_cpu_system
            online_cpus = d["cpu_stats"].get("online_cpus", len(d["cpu_stats"]["cpu_usage"]["percpu_usage"]))
            if system_delta > 0.0:
                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
            return cpu_percent, cpu_total, cpu_system

        # 计算IO
        def calculate_blkio_bytes(d):
            bytes_stats = graceful_chain_get(d, "blkio_stats", "io_service_bytes_recursive")
            if not bytes_stats:
                return 0, 0
            r = 0
            w = 0
            for s in bytes_stats:
                if s["op"] == "Read":
                    r += s["value"]
                elif s["op"] == "Write":
                    w += s["value"]
            return r, w

        # 计算网络
        def calculate_network_bytes(d):
            networks = graceful_chain_get(d, "networks")
            if not networks:
                return 0, 0
            r = 0
            t = 0
            for if_name, data in networks.items():
                r += data["rx_bytes"]
                t += data["tx_bytes"]
            return r, t

        def calculate_mem_bytes(d):
            mem_limit = d['memory_stats']['limit']
            mem_usage = d['memory_stats']['usage']
            return mem_usage, mem_limit

        def parse_unit(val, scale=1000):
            unit_ls = ['B', 'KB', 'MB', 'GB']
            unit_lv = 0
            while val >= scale:
                val /= scale
                unit_lv += 1
                if unit_lv == len(unit_ls)-1:
                    break
            return '{:.2f} {}'.format(val, unit_ls[unit_lv])

        if userName not in self.userStatsRtream:
            ctan = self.containers.get(userName)
            self.userStatsRtream[userName] = ctan.stats(decode=True)

        # pf_tm.tic()
        # 通过数据流获取信息
        raw_stats = self.userStatsRtream[userName].__next__()
        pre_cpu_stats = self.preCpuStats[userName]
        # pf_tm.toc('get stream')

        # cpu
        cpu_percent, cpu_total, cpu_system = calculate_cpu_percent2(raw_stats, pre_cpu_stats[0], pre_cpu_stats[1])
        self.preCpuStats[userName] = [cpu_total, cpu_system] # 更新usage
        # blk
        read_blk, write_blk = calculate_blkio_bytes(raw_stats)
        # net
        read_net, write_net = calculate_network_bytes(raw_stats)
        # mem
        mem_usage, mem_limit = calculate_mem_bytes(raw_stats)

        # pf_tm.toc('get cpu')

        # user gpu
        gpu_all_mem, gpu_used_mem, gpu_used_pcnt = 0, 0, 0
        gpu_num = nv.nvmlDeviceGetCount()
        for gpu_idx in range(gpu_num):
            h = nv.nvmlDeviceGetHandleByIndex(gpu_idx)
            running_process_obj_ls = nv.nvmlDeviceGetComputeRunningProcesses(h)
            for obj in running_process_obj_ls:
                process_pid = obj.pid
                process_raw_gpu_mem = obj.usedGpuMemory
                ctan_name = self.getCtanNameByPid(process_pid)
                if ctan_name == userName:
                    gpu_used_mem += process_raw_gpu_mem

            gpu_all_mem += nv.nvmlDeviceGetMemoryInfo(h).total
            # print('{} {}'.format(each_gpu_allmem, gpu_all_mem))

        ret_dt = {}
        ret_dt['id'] = raw_stats['id']
        ret_dt['pid'] = str(raw_stats['pids_stats']['current'])

        ret_dt['cpu_percent'] = '{:.2f}'.format(cpu_percent)
        ret_dt['read_blk'] = parse_unit(read_blk)
        ret_dt['write_blk'] = parse_unit(write_blk)
        ret_dt['read_net'] = parse_unit(read_net)
        ret_dt['write_net'] = parse_unit(write_net)
        ret_dt['mem_usage'] = parse_unit(mem_usage, scale=1024)
        ret_dt['mem_limit'] = parse_unit(mem_limit, scale=1024)

        ret_dt['mem_usage_pcnt'] = '{:.2f}'.format(mem_usage / mem_limit * 100)

        ret_dt['gpu_mem_usage'] = parse_unit(gpu_used_mem, 1024)
        ret_dt['gpu_mem_limit'] = parse_unit(gpu_all_mem, 1024)
        ret_dt['gpu_mem_usage_pcnt'] = '{:.2f}'.format(gpu_used_mem / gpu_all_mem * 100)

        return ret_dt

    def __get_gpu_info(self):
        def parse_unit(val, scale=1000):
            unit_ls = ['B', 'KB', 'MB', 'GB']
            unit_lv = 0
            while val >= scale:
                val /= scale
                unit_lv += 1
                if unit_lv == len(unit_ls)-1:
                    break
            return '{:.2f} {}'.format(val, unit_ls[unit_lv])

        sumInfo_ls = []
        process_ls = []

        nv.nvmlInit()
        gpuNum = nv.nvmlDeviceGetCount()
        # 遍历每块卡
        for gpuIdx in range(gpuNum):
            h = nv.nvmlDeviceGetHandleByIndex(gpuIdx)
            devName = nv.nvmlDeviceGetName(h).decode()
            raw_total_mem = nv.nvmlDeviceGetMemoryInfo(h).total
            total_mem = parse_unit(raw_total_mem, 1024)
            raw_used_mem = nv.nvmlDeviceGetMemoryInfo(h).used
            used_mem = parse_unit(raw_used_mem, 1024)
            gpu_util = '{:.2f}'.format(nv.nvmlDeviceGetUtilizationRates(h).gpu)
            gpu_mem_util = '{:.2f}'.format(raw_used_mem * 100 / raw_total_mem)

            tmp = {}
            tmp['gpu_idx'] = str(gpuIdx)
            tmp['dev_name'] = devName
            tmp['total_mem'] = total_mem
            tmp['used_mem'] = used_mem
            tmp['gpu_util'] = gpu_util
            tmp['gpu_mem_util'] = gpu_mem_util
            sumInfo_ls.append(tmp)

            runningProcessObj_ls = nv.nvmlDeviceGetComputeRunningProcesses(h)
            for obj in runningProcessObj_ls:
                process_pid = obj.pid
                process_type = 'C'
                process_raw_gpu_mem = obj.usedGpuMemory
                process_name = nv.nvmlSystemGetProcessName(process_pid).decode()
                ctanName = self.getCtanNameByPid(process_pid)

                tmp = {}
                tmp['gpu_idx'] = str(gpuIdx)
                tmp['dev_name'] = devName
                tmp['process_pid'] = str(process_pid)
                tmp['process_type'] = process_type
                tmp['process_name'] = process_name
                tmp['process_gpu_mem'] = parse_unit(process_raw_gpu_mem, 1024)
                tmp['ctan_name'] = ctanName
                process_ls.append(tmp)

            runningProcessObj_ls = nv.nvmlDeviceGetGraphicsRunningProcesses(h)
            for obj in runningProcessObj_ls:
                process_pid = obj.pid
                process_type = 'G'
                process_raw_gpu_mem = obj.usedGpuMemory
                process_name = nv.nvmlSystemGetProcessName(process_pid).decode()
                ctanName = self.getCtanNameByPid(process_pid)

                tmp = {}
                tmp['gpu_idx'] = str(gpuIdx)
                tmp['dev_name'] = devName
                tmp['process_pid'] = str(process_pid)
                tmp['process_type'] = process_type
                tmp['process_name'] = process_name
                tmp['process_gpu_mem'] = parse_unit(process_raw_gpu_mem, 1024)
                tmp['ctan_name'] = ctanName
                process_ls.append(tmp)
        return sumInfo_ls, process_ls

if __name__ == '__main__':
    um = labNode()
    # print('yes')
