import os
import socket, threading
import time
from collections import defaultdict
import dill, json
import bcrypt
from Crypto.Cipher import AES
import traceback

class SRVM(object):
    ACTION_START = 'start'
    ACTION_STOP = 'stop'
    ACTION_REMOVE = 'remove'
    ACTION_SOLID = 'solid'
    ACTION_PLSSYNC = 'plsSync'
    ACTION_PLSSAVE = 'plsSave'
    ACTION_SYNC =  'sync'
    ACTION_CREATEUSER = 'createUser'
    ACTION_ECHO = 'echo'
    ACTION_GETBASEINFO = 'baseInfo'
    ACTION_GETGPUINFO = 'gpuInfo'
    ACTION_GETCTANINFO = 'ctanInfo'
    ACTION_GETCNAMEBYPID = 'cNameByPid'

    def __init__(self, crypt_key, dataPath):
        # 服务器端口配置
        self.masterPort = 7777
        self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sk.bind(('192.168.0.11', self.masterPort))
        self.sk.listen(5)

        self.client_dt_addr = {
            '192.168.0.11': 'Amax',
            '192.168.0.33': 'Cmax',
            '192.168.0.44': 'Dmax',
            '192.168.0.55': 'Emax',
        }
        self.client_ls = list(self.client_dt_addr.values())
        self.connectedClient_ls = []
        self.addr_dt_client = {client: addr for addr, client in self.client_dt_addr.items()}
        self.conn_dt_client = {}
        self.echoArgs_dt_client = defaultdict(lambda :None)
        self.echoArgsFlag_dt_client = defaultdict(lambda :False)

        print('服务器监听端口地址： {}'.format(self.masterPort))
        threading.Thread(target=self.srvRun).start()  # 开启服务器接收

        # data
        self.dataPath = dataPath
        self.saveData_dt = {}
        self.dataDt_dt_userName = {}
        self.liveClient_dt_userName = {}

        # idx
        self.idxHportLs_dt_client = 0
        self.idxPW = 1
        self.idxMail = 2
        self.idxStarTime = 3
        self.idxRemark = 4
        self.idxPhone = 5
        
        # init the ciper
        def initCiper(key):
            # pad up with 0, the key len must be 16, 24, 32 byes long
            length = 16
            count = len(key)
            add = length - (count % length)
            key = key + ('\0' * add)
            return AES.new(key)
        self.__ciper = initCiper(key=crypt_key)
        del crypt_key

        # read the data dict
        if (not os.path.exists(self.dataPath)) or os.path.getsize(self.dataPath) == 0:
            print('init data into {}'.format(self.dataPath))
            self.dataDt_dt_userName = {}
            self.save()
        else:
            print('load data from {}'.format(self.dataPath))
            self.load()


    def connectedClientLs(self):
        return list(self.conn_dt_client.keys())

    def save(self, dataDt_dt_userName=None):
        print('开始存储数据')
        if dataDt_dt_userName is None:
            data_byte = dill.dumps([self.dataDt_dt_userName, self.liveClient_dt_userName])
        else:
            self.dataDt_dt_userName = dataDt_dt_userName
            data_byte = dill.dumps([dataDt_dt_userName, self.liveClient_dt_userName])

        # ctypt the data
        length = 16
        count = len(data_byte)
        add = length - (count % length)
        data_byte = data_byte + (b'\0' * add)
        wri_byte = self.__ciper.encrypt(data_byte) if self.__ciper is not None else data_byte
        with open(self.dataPath, 'wb') as f:
            dill.dump(wri_byte, f)  # convert to hex format and save it
        # 保存后再同步给各节点
        print('开始同步数据')
        self.syncAllNode()

    def load(self):
        # 本地载入文件
        with open(self.dataPath, 'rb') as f:
            rd_byte = dill.load(f)
        data_byte = self.__ciper.decrypt(rd_byte)
        data_byte = data_byte.rstrip(b'\0')
        # 本地加载
        self.dataDt_dt_userName, self.liveClient_dt_userName = dill.loads(data_byte)

    def syncAllNode(self):
        # 发送给各个节点进行同步
        for client in self.connectedClient_ls:
            self.syncOneNode(client)

    def syncOneNode(self, client):
        # 发送给单个节点进行同步
        cmd_ls = [client, 'all', self.ACTION_SYNC, self.dataDt_dt_userName]
        if client in self.conn_dt_client:
            conn = self.conn_dt_client[client]
            if conn is not None:
                conn.sendall( dill.dumps(cmd_ls) )
        else:
            print('{} not connect, 无法同步'.format(client))

    def srvRun(self):
        while True:
            conn, addrPort = self.sk.accept()
            client = self.client_dt_addr[addrPort[0]]
            self.conn_dt_client[client] = conn
            self.connectedClient_ls.append(client)
            # 开启多线程进行接收
            print('{} 连接， 处理线程开启'.format(client))
            t = threading.Thread(target=self.srvRecvHandler, args=(conn, addrPort))
            t.start()

    def srvRecvHandler(self, conn, addrPort):
        addr, port = addrPort
        client = self.client_dt_addr[addr]
        while True:
            try:
                cmd_byte = conn.recv(2048)
                if cmd_byte == b'':
                    print('{} 链接断开'.format(addr))
                    break
                cmd_ls = dill.loads(cmd_byte)
                print('接收{}数据,内容为{}'.format(client, cmd_ls))
                _, userName, action, args = cmd_ls  # 这里 _ 默认是‘srv’
                if action == self.ACTION_PLSSAVE:
                    dataDt_dt_userName = args
                    self.save(dataDt_dt_userName)
                elif action == self.ACTION_PLSSYNC:
                    self.syncOneNode(client)
                elif action == self.ACTION_ECHO:
                    self.echoArgs_dt_client[client] = args
                    self.echoArgsFlag_dt_client[client] = True
            except:
                traceback.print_exc()
                break
        conn.close()
        self.echoArgsFlag_dt_client[client] = False
        print('{} conn close'.format(client))
        self.conn_dt_client.pop(client)  # conn失效，去除
        self.connectedClient_ls.remove(client)

    def getEchoData(self, client) -> object:
        while True:
            time.sleep(0.5)
            if self.echoArgsFlag_dt_client[client]:
                rData = self.echoArgs_dt_client[client]
                self.echoArgsFlag_dt_client[client] = False
                print('echo接收，内容： {}'.format(rData))
                return rData

    def doAction(self, client, userName, action, args=None):
        if args is None: args = 'None'
        cmd_ls = [client, userName, action, args]
        if action != self.ACTION_ECHO:
            self.echoArgsFlag_dt_client[client] = False
        if client in self.conn_dt_client:
            conn = self.conn_dt_client[client]
            print('向{}发送数据，cmd_ls： {}'.format(client, cmd_ls))
            conn.sendall(dill.dumps(cmd_ls))
            return True
        else:
            print('{} 没有链接,无法发送action'.format(client))
            return False

    def createUser(self, client, userName, passwd='123456', mail='Null', remark='Null', phone='0'):
        args = {'passwd':passwd, 'mail':mail, 'remark':remark, 'phone':phone}
        rst = self.doAction(client, userName, action=self.ACTION_CREATEUSER, args=args)
        if rst and self.getEchoData(client) == 'success':
            self.liveClient_dt_userName[userName] = client
            self.save()
            return True
        else:
            return False

    def start(self, userName, client=None ):
        if client is None:
            client = self.liveClient_dt_userName[userName]
        rst = self.doAction(client, userName, self.ACTION_START)
        return rst and self.getEchoData(client) == 'success'


    def stop(self, userName, client=None ):
        if client is None:
            client = self.liveClient_dt_userName[userName]
        rst = self.doAction(client, userName, self.ACTION_STOP)
        return rst and self.getEchoData(client) == 'success'


    def remove(self, userName, client=None):
        if client is not None:  # 操作特定主机
            rst = self.doAction(client, userName, self.ACTION_REMOVE)
            return rst and self.getEchoData(client) == 'success'
        else:
            for client in self.connectedClient_ls:  # 所有主机同时操作
                rst = self.doAction(client, userName, self.ACTION_REMOVE)
                if not rst or self.getEchoData(client) != 'success':
                    return False
            return True

    def solid(self, userName, client=None):
        if client is None:
            client = self.liveClient_dt_userName[userName]
        rst = self.doAction(client, userName, self.ACTION_SOLID)
        return rst and self.getEchoData(client) == 'success'

    def switch(self, userName, clientSrc, clientDst):
        if clientSrc != self.liveClient_dt_userName[userName]:
            print('{} not running at {}'.format(userName, clientSrc))
            return False
        if not self.solid(userName, clientSrc): return False
        if not self.start(userName, clientDst): return False
        self.liveClient_dt_userName[userName] = clientDst
        self.save()
        return True

    def getCtansBaseInfoDt(self):
        baseInfoDt_dt_client = {}
        res = {}
        for client in self.connectedClient_ls:
            rst = self.doAction(client, userName='all', action=self.ACTION_GETBASEINFO)
            if rst:
                baseInfoDt_dt_client[client] = self.getEchoData(client)

        for userName in self.dataDt_dt_userName:
            liveClient = self.liveClient_dt_userName[userName]
            res[userName] = baseInfoDt_dt_client[liveClient][userName]
        # {user1: [user1, 'Amax:29000~29009', 'RUNNING', ip, uptime, remark],
        # user2: [user2, 'Bmax:29000~29009', 'STOPPED', ip, uptime, remark]}
        return res

    # 验证密码是否有效
    def validUserPW(self, userName, PW, admin=False):
        if admin:  # check the admin passwd
            return PW == '123456kx'

        hashedPW = self.dataDt_dt_userName[userName][self.idxPW]
        return bcrypt.checkpw(PW.encode(), hashedPW)

    def getRuningUsername(self):
        baseInfoDt = self.getCtansBaseInfoDt()
        userName_ls = []
        for userName, baseInfo in baseInfoDt.items():
            if baseInfo[2] == 'RUNNING':
                userName_ls.append(userName)
        return userName_ls

    # 更改信息
    def changeCtanInfo(self, userName, idx, newVal):
        self.dataDt_dt_userName[userName][idx] = newVal
        self.save()
        return True
    
    def changeCtanMail(self, userName, newMail):
        return self.changeCtanInfo(userName, self.idxMail, newMail)

    def changeCtanMark(self, userName, newMark):
        return self.changeCtanInfo(userName, self.idxRemark, newMark)

    def change_phone(self, userName, newPhone):
        return self.changeCtanInfo(userName, self.idxPhone, newPhone)

    def changeCtanPW(self, userName, newPW):
        newHashedPW = bcrypt.hashpw(newPW.encode(), bcrypt.gensalt(10))
        return self.changeCtanInfo(userName, self.idxPW, newHashedPW)

    def resetStartime(self, userName):
        newtimeStamp = int(time.time())
        self.dataDt_dt_userName[userName][self.idxStarTime] = newtimeStamp
        self.save()
        return True

    # 获取用户信息
    def getUserPrivace(self, user_name):
        dataDt = self.dataDt_dt_userName[user_name]
        phone = dataDt[self.idxPhone]
        mail = dataDt[self.idxMail]
        ret = '{}, phone is {}, mail is {}'.format(user_name, phone, mail)
        return ret

    def getCtanInfo(self, client, userName):
        rst = self.doAction(client, userName=userName, action=self.ACTION_GETCTANINFO)
        if rst:
            return self.getEchoData(client)
        return None

    def getGPUInfo(self, client):
        rst = self.doAction(client, userName='all', action=self.ACTION_GETGPUINFO)
        if rst:
            return self.getEchoData(client)
        return None

    def getCtanNameByPid(self, client, pid):
        rst = self.doAction(client, userName='all', action=self.ACTION_GETCNAMEBYPID, args=pid)
        if rst:
            return self.getEchoData(client)
        return None

if __name__ == '__main__':
    srvm = SRVM('1234567890', 'srvm.dt')
    srvm.createUser('Amax', 'kx', '123456', '1@1.com', '1', '1')
    srvm.stop('kx')
    srvm.remove('kx')
    srvm.createUser('Amax', 'kx', '123456', '1@1.com', '2', '2')
    srvm.solid('kx')
