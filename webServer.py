# -*- coding:utf-8 -*-
import configparser
import tornado.ioloop
import tornado.web
import tornado.httpserver
import os, sys, getopt, psutil
import traceback
from labMaster import SRVM
import re
import xml.etree.cElementTree as et

# settings
settings = {
    "static_path": os.path.join(os.path.dirname(__file__), "www/dist"),
    "debug": True,
}

host_name = None
# um = SRVM('1234567890',  'srvm.dt')
um = None
machine_name = None


# Deal with CORS problem
class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', ' PUT, DELETE, OPTIONS')

    def options(self):
        # no body
        self.set_status(204)
        self.finish()

    def prepare(self):
        # print(self.request.host)
        fullHost = self.request.host
        fullHostSpilt_ls = fullHost.split(':')
        assert len(fullHostSpilt_ls) == 2, 'port is missing'
        net, port = fullHostSpilt_ls[0], fullHostSpilt_ls[1]
        if net != 'www.a207.xyz' and net != 'a207.xyz':
            print('host is {}, not valid'.format(net))
            self.send_error(404)
            return
        if self.request.protocol == "http":
            redirect_str = 'https://{}:{}'.format(net, int(port) + 1)
            # print('redirect {}'.format(redirect_str))
            self.redirect(redirect_str, permanent=True)


# Index Page: Query all users states
class MainHandler(BaseHandler):
    def get(self):
        print("[Server] Query Request: ")
        items = {}
        try:
            items = um.getCtansBaseInfoDt()
        except Exception:
            print("[Server] Query Error!")
            traceback.print_exc()
        self.render("www/index.html", items=items)


# Register Page:
class RegisterHandler(BaseHandler):
    def get(self):
        self.render("./www/register.html")


class startHandler(BaseHandler):
    def get(self, username):

        res = "failed"
        try:
            if um.start(username):
                res = "succeed"
        except Exception:
            print("[Server] User Start Error!")
            traceback.print_exc()
        print("[Server] Start Request: " + username + ": " + res)
        self.write(res)


class stopHandler(BaseHandler):
    def get(self, username):

        res = "failed"
        try:
            if um.stop(username):
                res = "succeed"
        except Exception:
            print("[Server] User Stop Error!")
            traceback.print_exc()
        print("[Server] Stop Request: " + username + ": " + res)
        self.write(res)


# add a new user
class addUserHandler(BaseHandler):
    def get(self, hostName, username, remark, passwd, mail, phone, managerPasswd):

        print("[Server] Register Request: " + username + ": dealing...")
        res = "failed"
        # 验证管理员密码
        if not um.validUserPW(hostName, managerPasswd, admin=True):
            self.write("invManagePass")
            return
        try:
            if um.createUser(client=hostName, userName=username, passwd=passwd, mail=mail, remark=remark, phone=phone):
                res = "succeed"
            # time.sleep(10)
            # res = "succeed"
        except Exception:
            traceback.print_exc()
            print("[Server] Add User Error!")
        print("[Server] Register Done: " + username + ": " + res)
        self.write(res)


# delete a user
class deleteUserHandler(BaseHandler):
    def get(self, username):
        res = "failed"
        try:

            if um.remove(username):
                res = "succeed"
        except Exception as e:
            print("[Server] Del User Error!")
        print("[Server] Delete Request: " + username + ": " + res)
        self.write(res)

class verifyPasswordHandler(BaseHandler):
    def get(self, username, passwd):

        # print('valid passwd {}'.format(passwd))
        res = "failed"
        try:
            if um.validUserPW(username, passwd):
                res = "succeed"
            elif um.validUserPW(host_name, passwd, admin=True):
                res = "succeed"
        except Exception:
            traceback.print_exc()
        self.write(res)

    def post(self):

        username = self.get_argument('name')
        passwd = self.get_argument('passwd')

        res = "Wrong"
        try:
            if um.validUserPW(username, passwd):
                res = "Right"
            if um.validUserPW(host_name, passwd, admin=True):
                res = "Right"
        except Exception:
            traceback.print_exc()
        self.write(res)

class updateGPUStatusHandler(BaseHandler):
    def get(self):

        print('update gpu')
        status = os.popen('nvidia-smi').readlines()

        res = '<br /><br />'
        for line in status:
            match = re.match(r'^\| *(\d+) *(\d+) *.*(\d+)MiB *\|$', line)
            name = ''
            if match:
                try:
                    pid = match.group(2)
                    ctan_name = um.getCtanNameByPid('Amax', int(pid))
                    name = '%12s |' % ctan_name
                except:
                    name = '%12s |' % 'server'
            else:
                pass
            res += '<br>' + line.strip().replace(' ', '&nbsp;') + name.replace(' ', '&nbsp;') + '</br>'
        return self.write(res)

class GPUStatusHandler(BaseHandler):
    def get(self):
        self.render("./www/gpu_status.html")

class updateAREStatusHandler(BaseHandler):
    def get(self):

        # print('update cpu')
        # CPU 和 内存
        column_width = 300  # 表格没列宽度
        res = ''
        # GPU 总的使用情况
        gpu_sum, gpu_process_ls = um.getGPUInfo('Amax')
        # GPU总表格
        res += '<h3>GPU信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">GPU_id</th>' \
               '<th class="user_info_columnStyle">GPU_name</th>' \
               '<th class="user_info_columnStyle">GPU_mem</th>' \
               '<th class="user_info_columnStyle">GPU_util</th>' \
               '</tr>'
        for i in range(len(gpu_sum)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_idx"] + '</td>' \
                                                                                      '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_sum[i]["dev_name"] + '</td>'
            res += '<td class=\"user_info_columnStyle_s\">'
            # gpu_perc
            gpu_m_usage = gpu_sum[i]['used_mem']
            gpu_m_limit = gpu_sum[i]['total_mem']
            gpu_m_perc = float(gpu_sum[i]['gpu_mem_util'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            width_gpu = gpu_m_perc if gpu_m_perc > 2 else 2
            res += '<span style=\"text-align:center;background-color:' + mem_color
            res += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            res += str(width_gpu / 100 * column_width)
            res += 'px\">'
            res += gpu_m_usage + ' / ' + gpu_m_limit
            res += '</span>'
            res += '</td>'
            res += '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_util"] + '%</td>'

        res += '</table><br><br>'
        # gpu process表格
        res += '<h3>GPU process信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">process_type</th>' \
               '<th class="user_info_columnStyle">gpu_idx</th>' \
               '<th class="user_info_columnStyle">process_pid</th>' \
               '<th class="user_info_columnStyle">process_name</th>' \
               '<th class="user_info_columnStyle">dev_name</th>' \
               '<th class="user_info_columnStyle">process_gpu_mem</th>' \
               '<th class="user_info_columnStyle">user_name</th>' \
               '</tr>'
        for i in range(len(gpu_process_ls)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_type"] + '</td>' \
                                                                                                  '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["gpu_idx"] + '</td>' \
                                                  '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "process_pid"] + '</td>'
            lenOfProcessName = len(gpu_process_ls[i]["process_name"])
            if lenOfProcessName > 20:
                res += '<td class=\"user_info_columnStyle_s\" title=\"'
                res += gpu_process_ls[i]["process_name"]
                res += '\">'
                res += gpu_process_ls[i]["process_name"][:20] + '...'
            else:
                res += '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_name"] + '</td>'
            res += '</td>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["dev_name"] + '</td>' \
                                                                                              '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["process_gpu_mem"] + '</td>' \
                                                          '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "ctan_name"] + '</td>'

        res += '</table><br><br>'

        # 用户的资源
        res += '<h3>用户资源信息</h3>'
        res_infos = {}
        userList = um.getRuningUsername()
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">Name</th>' \
               '<th class="user_info_columnStyle">CPU</th>' \
               '<th class="user_info_columnStyle">MEM</th>' \
               '<th class="user_info_columnStyle">IO R/W</th>' \
               '<th class="user_info_columnStyle">NET R/W</th>' \
               '<th class="user_info_columnStyle">GPU_MEM</th>' \
               '</tr>'
        for name in userList:
            res_infos[name] = um.getCtanInfo('Amax', name)
            if res_infos[name] is None:
                continue
            thisLine = '<tr>'
            # column 1: name
            thisLine += '<td class=\"user_info_columnStyle_s\">' + name + '</td>'
            # column 2: cpu
            cpu_perc = float(res_infos[name]['cpu_percent'])
            cpu_color = '#00ff00'
            if cpu_perc >= 2400 * 0.8:
                cpu_color = '#ff0000'
            else:
                cpu_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + cpu_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(cpu_perc / 2400 * column_width) if cpu_perc / 12 > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += str(cpu_perc)
            thisLine += '%</span>'
            thisLine += '</td>'
            # column 3: mem
            m_usage = res_infos[name]['mem_usage']
            m_limit = res_infos[name]['mem_limit']
            m_perc = float(res_infos[name]['mem_usage_pcnt'])
            mem_color = ''
            if m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(m_perc / 100 * column_width) if m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += m_usage + ' / ' + m_limit
            thisLine += '</span>'
            thisLine += '</td>'
            # column 4:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_net'] + ' / ' + \
                        res_infos[name]['write_net'] + '</td>'
            # column 5:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_blk'] + ' / ' + \
                        res_infos[name]['write_blk'] + '</td>'

            gpu_m_usage = res_infos[name]['gpu_mem_usage']
            gpu_m_limit = res_infos[name]['gpu_mem_limit']
            gpu_m_perc = float(res_infos[name]['gpu_mem_usage_pcnt'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(gpu_m_perc / 100 * column_width) if gpu_m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += gpu_m_usage + ' / ' + gpu_m_limit
            thisLine += '</span>'
            thisLine += '</td>'

            # sum
            res += thisLine
        res += '</table>'
        # print(res)
        return self.write(res)

class updateBREStatusHandler(BaseHandler):
    def get(self):

        # print('update cpu')
        # CPU 和 内存
        column_width = 300  # 表格没列宽度
        res = ''
        # GPU 总的使用情况
        gpu_sum, gpu_process_ls = um.getGPUInfo('Bmax')
        # GPU总表格
        res += '<h3>GPU信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">GPU_id</th>' \
               '<th class="user_info_columnStyle">GPU_name</th>' \
               '<th class="user_info_columnStyle">GPU_mem</th>' \
               '<th class="user_info_columnStyle">GPU_util</th>' \
               '</tr>'
        for i in range(len(gpu_sum)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_idx"] + '</td>' \
                                                                                      '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_sum[i]["dev_name"] + '</td>'
            res += '<td class=\"user_info_columnStyle_s\">'
            # gpu_perc
            gpu_m_usage = gpu_sum[i]['used_mem']
            gpu_m_limit = gpu_sum[i]['total_mem']
            gpu_m_perc = float(gpu_sum[i]['gpu_mem_util'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            width_gpu = gpu_m_perc if gpu_m_perc > 2 else 2
            res += '<span style=\"text-align:center;background-color:' + mem_color
            res += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            res += str(width_gpu / 100 * column_width)
            res += 'px\">'
            res += gpu_m_usage + ' / ' + gpu_m_limit
            res += '</span>'
            res += '</td>'
            res += '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_util"] + '%</td>'

        res += '</table><br><br>'
        # gpu process表格
        res += '<h3>GPU process信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">process_type</th>' \
               '<th class="user_info_columnStyle">gpu_idx</th>' \
               '<th class="user_info_columnStyle">process_pid</th>' \
               '<th class="user_info_columnStyle">process_name</th>' \
               '<th class="user_info_columnStyle">dev_name</th>' \
               '<th class="user_info_columnStyle">process_gpu_mem</th>' \
               '<th class="user_info_columnStyle">user_name</th>' \
               '</tr>'
        for i in range(len(gpu_process_ls)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_type"] + '</td>' \
                                                                                                  '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["gpu_idx"] + '</td>' \
                                                  '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "process_pid"] + '</td>'
            lenOfProcessName = len(gpu_process_ls[i]["process_name"])
            if lenOfProcessName > 20:
                res += '<td class=\"user_info_columnStyle_s\" title=\"'
                res += gpu_process_ls[i]["process_name"]
                res += '\">'
                res += gpu_process_ls[i]["process_name"][:20] + '...'
            else:
                res += '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_name"] + '</td>'
            res += '</td>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["dev_name"] + '</td>' \
                                                                                              '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["process_gpu_mem"] + '</td>' \
                                                          '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "ctan_name"] + '</td>'

        res += '</table><br><br>'

        # 用户的资源
        res += '<h3>用户资源信息</h3>'
        res_infos = {}
        userList = um.getRuningUsername()
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">Name</th>' \
               '<th class="user_info_columnStyle">CPU</th>' \
               '<th class="user_info_columnStyle">MEM</th>' \
               '<th class="user_info_columnStyle">IO R/W</th>' \
               '<th class="user_info_columnStyle">NET R/W</th>' \
               '<th class="user_info_columnStyle">GPU_MEM</th>' \
               '</tr>'
        for name in userList:
            res_infos[name] = um.getCtanInfo('Bmax', name)
            if res_infos[name] is None:
                continue
            thisLine = '<tr>'
            # column 1: name
            thisLine += '<td class=\"user_info_columnStyle_s\">' + name + '</td>'
            # column 2: cpu
            cpu_perc = float(res_infos[name]['cpu_percent'])
            cpu_color = '#00ff00'
            if cpu_perc >= 2400 * 0.8:
                cpu_color = '#ff0000'
            else:
                cpu_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + cpu_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(cpu_perc / 2400 * column_width) if cpu_perc / 12 > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += str(cpu_perc)
            thisLine += '%</span>'
            thisLine += '</td>'
            # column 3: mem
            m_usage = res_infos[name]['mem_usage']
            m_limit = res_infos[name]['mem_limit']
            m_perc = float(res_infos[name]['mem_usage_pcnt'])
            mem_color = ''
            if m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(m_perc / 100 * column_width) if m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += m_usage + ' / ' + m_limit
            thisLine += '</span>'
            thisLine += '</td>'
            # column 4:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_net'] + ' / ' + \
                        res_infos[name]['write_net'] + '</td>'
            # column 5:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_blk'] + ' / ' + \
                        res_infos[name]['write_blk'] + '</td>'

            gpu_m_usage = res_infos[name]['gpu_mem_usage']
            gpu_m_limit = res_infos[name]['gpu_mem_limit']
            gpu_m_perc = float(res_infos[name]['gpu_mem_usage_pcnt'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(gpu_m_perc / 100 * column_width) if gpu_m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += gpu_m_usage + ' / ' + gpu_m_limit
            thisLine += '</span>'
            thisLine += '</td>'

            # sum
            res += thisLine
        res += '</table>'
        # print(res)
        return self.write(res)

class updateCREStatusHandler(BaseHandler):
    def get(self):

        # print('update cpu')
        # CPU 和 内存
        column_width = 300  # 表格没列宽度
        res = ''
        # GPU 总的使用情况
        gpu_sum, gpu_process_ls = um.getGPUInfo('Cmax')
        # GPU总表格
        res += '<h3>GPU信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">GPU_id</th>' \
               '<th class="user_info_columnStyle">GPU_name</th>' \
               '<th class="user_info_columnStyle">GPU_mem</th>' \
               '<th class="user_info_columnStyle">GPU_util</th>' \
               '</tr>'
        for i in range(len(gpu_sum)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_idx"] + '</td>' \
                                                                                      '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_sum[i]["dev_name"] + '</td>'
            res += '<td class=\"user_info_columnStyle_s\">'
            # gpu_perc
            gpu_m_usage = gpu_sum[i]['used_mem']
            gpu_m_limit = gpu_sum[i]['total_mem']
            gpu_m_perc = float(gpu_sum[i]['gpu_mem_util'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            width_gpu = gpu_m_perc if gpu_m_perc > 2 else 2
            res += '<span style=\"text-align:center;background-color:' + mem_color
            res += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            res += str(width_gpu / 100 * column_width)
            res += 'px\">'
            res += gpu_m_usage + ' / ' + gpu_m_limit
            res += '</span>'
            res += '</td>'
            res += '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_util"] + '%</td>'

        res += '</table><br><br>'
        # gpu process表格
        res += '<h3>GPU process信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">process_type</th>' \
               '<th class="user_info_columnStyle">gpu_idx</th>' \
               '<th class="user_info_columnStyle">process_pid</th>' \
               '<th class="user_info_columnStyle">process_name</th>' \
               '<th class="user_info_columnStyle">dev_name</th>' \
               '<th class="user_info_columnStyle">process_gpu_mem</th>' \
               '<th class="user_info_columnStyle">user_name</th>' \
               '</tr>'
        for i in range(len(gpu_process_ls)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_type"] + '</td>' \
                                                                                                  '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["gpu_idx"] + '</td>' \
                                                  '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "process_pid"] + '</td>'
            lenOfProcessName = len(gpu_process_ls[i]["process_name"])
            if lenOfProcessName > 20:
                res += '<td class=\"user_info_columnStyle_s\" title=\"'
                res += gpu_process_ls[i]["process_name"]
                res += '\">'
                res += gpu_process_ls[i]["process_name"][:20] + '...'
            else:
                res += '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_name"] + '</td>'
            res += '</td>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["dev_name"] + '</td>' \
                                                                                              '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["process_gpu_mem"] + '</td>' \
                                                          '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "ctan_name"] + '</td>'

        res += '</table><br><br>'

        # 用户的资源
        res += '<h3>用户资源信息</h3>'
        res_infos = {}
        userList = um.getRuningUsername()
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">Name</th>' \
               '<th class="user_info_columnStyle">CPU</th>' \
               '<th class="user_info_columnStyle">MEM</th>' \
               '<th class="user_info_columnStyle">IO R/W</th>' \
               '<th class="user_info_columnStyle">NET R/W</th>' \
               '<th class="user_info_columnStyle">GPU_MEM</th>' \
               '</tr>'
        for name in userList:
            res_infos[name] = um.getCtanInfo('Cmax', name)
            if res_infos[name] is None:
                continue
            thisLine = '<tr>'
            # column 1: name
            thisLine += '<td class=\"user_info_columnStyle_s\">' + name + '</td>'
            # column 2: cpu
            cpu_perc = float(res_infos[name]['cpu_percent'])
            cpu_color = '#00ff00'
            if cpu_perc >= 2400 * 0.8:
                cpu_color = '#ff0000'
            else:
                cpu_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + cpu_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(cpu_perc / 2400 * column_width) if cpu_perc / 12 > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += str(cpu_perc)
            thisLine += '%</span>'
            thisLine += '</td>'
            # column 3: mem
            m_usage = res_infos[name]['mem_usage']
            m_limit = res_infos[name]['mem_limit']
            m_perc = float(res_infos[name]['mem_usage_pcnt'])
            mem_color = ''
            if m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(m_perc / 100 * column_width) if m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += m_usage + ' / ' + m_limit
            thisLine += '</span>'
            thisLine += '</td>'
            # column 4:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_net'] + ' / ' + \
                        res_infos[name]['write_net'] + '</td>'
            # column 5:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_blk'] + ' / ' + \
                        res_infos[name]['write_blk'] + '</td>'

            gpu_m_usage = res_infos[name]['gpu_mem_usage']
            gpu_m_limit = res_infos[name]['gpu_mem_limit']
            gpu_m_perc = float(res_infos[name]['gpu_mem_usage_pcnt'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(gpu_m_perc / 100 * column_width) if gpu_m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += gpu_m_usage + ' / ' + gpu_m_limit
            thisLine += '</span>'
            thisLine += '</td>'

            # sum
            res += thisLine
        res += '</table>'
        # print(res)
        return self.write(res)


class updateDREStatusHandler(BaseHandler):
    def get(self):

        # print('update cpu')
        # CPU 和 内存
        column_width = 300  # 表格没列宽度
        res = ''
        # GPU 总的使用情况
        gpu_sum, gpu_process_ls = um.getGPUInfo('Dmax')
        # GPU总表格
        res += '<h3>GPU信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">GPU_id</th>' \
               '<th class="user_info_columnStyle">GPU_name</th>' \
               '<th class="user_info_columnStyle">GPU_mem</th>' \
               '<th class="user_info_columnStyle">GPU_util</th>' \
               '</tr>'
        for i in range(len(gpu_sum)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_idx"] + '</td>' \
                                                                                      '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_sum[i]["dev_name"] + '</td>'
            res += '<td class=\"user_info_columnStyle_s\">'
            # gpu_perc
            gpu_m_usage = gpu_sum[i]['used_mem']
            gpu_m_limit = gpu_sum[i]['total_mem']
            gpu_m_perc = float(gpu_sum[i]['gpu_mem_util'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            width_gpu = gpu_m_perc if gpu_m_perc > 2 else 2
            res += '<span style=\"text-align:center;background-color:' + mem_color
            res += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            res += str(width_gpu / 100 * column_width)
            res += 'px\">'
            res += gpu_m_usage + ' / ' + gpu_m_limit
            res += '</span>'
            res += '</td>'
            res += '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_util"] + '%</td>'

        res += '</table><br><br>'
        # gpu process表格
        res += '<h3>GPU process信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">process_type</th>' \
               '<th class="user_info_columnStyle">gpu_idx</th>' \
               '<th class="user_info_columnStyle">process_pid</th>' \
               '<th class="user_info_columnStyle">process_name</th>' \
               '<th class="user_info_columnStyle">dev_name</th>' \
               '<th class="user_info_columnStyle">process_gpu_mem</th>' \
               '<th class="user_info_columnStyle">user_name</th>' \
               '</tr>'
        for i in range(len(gpu_process_ls)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_type"] + '</td>' \
                                                                                                  '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["gpu_idx"] + '</td>' \
                                                  '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "process_pid"] + '</td>'
            lenOfProcessName = len(gpu_process_ls[i]["process_name"])
            if lenOfProcessName > 20:
                res += '<td class=\"user_info_columnStyle_s\" title=\"'
                res += gpu_process_ls[i]["process_name"]
                res += '\">'
                res += gpu_process_ls[i]["process_name"][:20] + '...'
            else:
                res += '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_name"] + '</td>'
            res += '</td>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["dev_name"] + '</td>' \
                                                                                              '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["process_gpu_mem"] + '</td>' \
                                                          '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "ctan_name"] + '</td>'

        res += '</table><br><br>'

        # 用户的资源
        res += '<h3>用户资源信息</h3>'
        res_infos = {}
        userList = um.getRuningUsername()
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">Name</th>' \
               '<th class="user_info_columnStyle">CPU</th>' \
               '<th class="user_info_columnStyle">MEM</th>' \
               '<th class="user_info_columnStyle">IO R/W</th>' \
               '<th class="user_info_columnStyle">NET R/W</th>' \
               '<th class="user_info_columnStyle">GPU_MEM</th>' \
               '</tr>'
        for name in userList:
            res_infos[name] = um.getCtanInfo('Dmax', name)
            if res_infos[name] is None:
                continue
            thisLine = '<tr>'
            # column 1: name
            thisLine += '<td class=\"user_info_columnStyle_s\">' + name + '</td>'
            # column 2: cpu
            cpu_perc = float(res_infos[name]['cpu_percent'])
            cpu_color = '#00ff00'
            if cpu_perc >= 2400 * 0.8:
                cpu_color = '#ff0000'
            else:
                cpu_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + cpu_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(cpu_perc / 2400 * column_width) if cpu_perc / 12 > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += str(cpu_perc)
            thisLine += '%</span>'
            thisLine += '</td>'
            # column 3: mem
            m_usage = res_infos[name]['mem_usage']
            m_limit = res_infos[name]['mem_limit']
            m_perc = float(res_infos[name]['mem_usage_pcnt'])
            mem_color = ''
            if m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(m_perc / 100 * column_width) if m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += m_usage + ' / ' + m_limit
            thisLine += '</span>'
            thisLine += '</td>'
            # column 4:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_net'] + ' / ' + \
                        res_infos[name]['write_net'] + '</td>'
            # column 5:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_blk'] + ' / ' + \
                        res_infos[name]['write_blk'] + '</td>'

            gpu_m_usage = res_infos[name]['gpu_mem_usage']
            gpu_m_limit = res_infos[name]['gpu_mem_limit']
            gpu_m_perc = float(res_infos[name]['gpu_mem_usage_pcnt'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(gpu_m_perc / 100 * column_width) if gpu_m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += gpu_m_usage + ' / ' + gpu_m_limit
            thisLine += '</span>'
            thisLine += '</td>'

            # sum
            res += thisLine
        res += '</table>'
        # print(res)
        return self.write(res)

class updateEREStatusHandler(BaseHandler):
    def get(self):

        # print('update cpu')
        # CPU 和 内存
        column_width = 300  # 表格没列宽度
        res = ''
        # GPU 总的使用情况
        gpu_sum, gpu_process_ls = um.getGPUInfo('Emax')
        # GPU总表格
        res += '<h3>GPU信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">GPU_id</th>' \
               '<th class="user_info_columnStyle">GPU_name</th>' \
               '<th class="user_info_columnStyle">GPU_mem</th>' \
               '<th class="user_info_columnStyle">GPU_util</th>' \
               '</tr>'
        for i in range(len(gpu_sum)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_idx"] + '</td>' \
                                                                                      '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_sum[i]["dev_name"] + '</td>'
            res += '<td class=\"user_info_columnStyle_s\">'
            # gpu_perc
            gpu_m_usage = gpu_sum[i]['used_mem']
            gpu_m_limit = gpu_sum[i]['total_mem']
            gpu_m_perc = float(gpu_sum[i]['gpu_mem_util'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            width_gpu = gpu_m_perc if gpu_m_perc > 2 else 2
            res += '<span style=\"text-align:center;background-color:' + mem_color
            res += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            res += str(width_gpu / 100 * column_width)
            res += 'px\">'
            res += gpu_m_usage + ' / ' + gpu_m_limit
            res += '</span>'
            res += '</td>'
            res += '<td class=\"user_info_columnStyle_s\">' + gpu_sum[i]["gpu_util"] + '%</td>'

        res += '</table><br><br>'
        # gpu process表格
        res += '<h3>GPU process信息</h3>'
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">process_type</th>' \
               '<th class="user_info_columnStyle">gpu_idx</th>' \
               '<th class="user_info_columnStyle">process_pid</th>' \
               '<th class="user_info_columnStyle">process_name</th>' \
               '<th class="user_info_columnStyle">dev_name</th>' \
               '<th class="user_info_columnStyle">process_gpu_mem</th>' \
               '<th class="user_info_columnStyle">user_name</th>' \
               '</tr>'
        for i in range(len(gpu_process_ls)):
            res += '<tr>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_type"] + '</td>' \
                                                                                                  '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["gpu_idx"] + '</td>' \
                                                  '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "process_pid"] + '</td>'
            lenOfProcessName = len(gpu_process_ls[i]["process_name"])
            if lenOfProcessName > 20:
                res += '<td class=\"user_info_columnStyle_s\" title=\"'
                res += gpu_process_ls[i]["process_name"]
                res += '\">'
                res += gpu_process_ls[i]["process_name"][:20] + '...'
            else:
                res += '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["process_name"] + '</td>'
            res += '</td>' \
                   '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i]["dev_name"] + '</td>' \
                                                                                              '<td class=\"user_info_columnStyle_s\">' + \
                   gpu_process_ls[i]["process_gpu_mem"] + '</td>' \
                                                          '<td class=\"user_info_columnStyle_s\">' + gpu_process_ls[i][
                       "ctan_name"] + '</td>'

        res += '</table><br><br>'

        # 用户的资源
        res += '<h3>用户资源信息</h3>'
        res_infos = {}
        userList = um.getRuningUsername()
        res += '<table align="center">' \
               '<tr>' \
               '<th class="user_info_columnStyle">Name</th>' \
               '<th class="user_info_columnStyle">CPU</th>' \
               '<th class="user_info_columnStyle">MEM</th>' \
               '<th class="user_info_columnStyle">IO R/W</th>' \
               '<th class="user_info_columnStyle">NET R/W</th>' \
               '<th class="user_info_columnStyle">GPU_MEM</th>' \
               '</tr>'
        for name in userList:
            res_infos[name] = um.getCtanInfo('Emax', name)
            if res_infos[name] is None:
                continue
            thisLine = '<tr>'
            # column 1: name
            thisLine += '<td class=\"user_info_columnStyle_s\">' + name + '</td>'
            # column 2: cpu
            cpu_perc = float(res_infos[name]['cpu_percent'])
            cpu_color = '#00ff00'
            if cpu_perc >= 2400 * 0.8:
                cpu_color = '#ff0000'
            else:
                cpu_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + cpu_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(cpu_perc / 2400 * column_width) if cpu_perc / 12 > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += str(cpu_perc)
            thisLine += '%</span>'
            thisLine += '</td>'
            # column 3: mem
            m_usage = res_infos[name]['mem_usage']
            m_limit = res_infos[name]['mem_limit']
            m_perc = float(res_infos[name]['mem_usage_pcnt'])
            mem_color = ''
            if m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(m_perc / 100 * column_width) if m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += m_usage + ' / ' + m_limit
            thisLine += '</span>'
            thisLine += '</td>'
            # column 4:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_net'] + ' / ' + \
                        res_infos[name]['write_net'] + '</td>'
            # column 5:
            thisLine += '<td class=\"user_info_columnStyle_s\">' + res_infos[name]['read_blk'] + ' / ' + \
                        res_infos[name]['write_blk'] + '</td>'

            gpu_m_usage = res_infos[name]['gpu_mem_usage']
            gpu_m_limit = res_infos[name]['gpu_mem_limit']
            gpu_m_perc = float(res_infos[name]['gpu_mem_usage_pcnt'])
            mem_color = ''
            if gpu_m_perc >= 80:
                mem_color = '#ff0000'
            else:
                mem_color = '#00ff00'
            thisLine += '<td class=\"user_info_columnStyle_s\">'
            thisLine += '<span style=\"text-align:center;background-color:' + mem_color
            thisLine += ';display:-moz-inline-box;display:inline-block;white-space:nowrap;width:'
            width_ps = str(gpu_m_perc / 100 * column_width) if gpu_m_perc > 2 else str(2)
            thisLine += width_ps
            thisLine += 'px\">'
            thisLine += gpu_m_usage + ' / ' + gpu_m_limit
            thisLine += '</span>'
            thisLine += '</td>'

            # sum
            res += thisLine
        res += '</table>'
        # print(res)
        return self.write(res)

class AREStatusHandler(BaseHandler):
    def get(self):
        self.render("./www/cpu_status_amax.html")
class BREStatusHandler(BaseHandler):
    def get(self):
        self.render("./www/cpu_status_bmax.html")
class CREStatusHandler(BaseHandler):
    def get(self):
        self.render("./www/cpu_status_cmax.html")
class DREStatusHandler(BaseHandler):
    def get(self):
        self.render("./www/cpu_status_dmax.html")
class EREStatusHandler(BaseHandler):
    def get(self):
        self.render("./www/cpu_status_emax.html")



# 新:CPU饼图更新函数

class cpuUtils_MainHandler(BaseHandler):
    def get(self):
        self.render("./www/cpu_status.html")


class cpuUtils_AjaxHandler(BaseHandler):
    def post(self):
        cpu_util = psutil.cpu_percent(None)
        mem_util = psutil.virtual_memory().percent
        import datetime
        time_obj = datetime.datetime.now()
        time_str = datetime.datetime.strftime(time_obj, '%Y-%m-%d %H:%M:%S')
        _time = time_str
        dict = {"c": cpu_util, "m": mem_util, "time": _time}
        self.write(dict)


# 更新用户隐私信息
class updatePrivacyHandler(BaseHandler):
    def get(self, username, new_mail, new_addition, new_phone):
        res = "failed"
        try:

            if (new_mail != "NotModified"):
                print('change {} mail'.format(username))
                um.changeCtanMail(username, new_mail)
                print('mail of {} is changed'.format(username))
            if (new_addition != "NotModified"):
                print('change {} addition'.format(username))
                um.changeCtanMark(username, new_addition)
                print('mark of {} is changed'.format(username))
            if (new_phone != "NotModified"):
                print('change {} phone'.format(username))
                um.change_phone(username, new_phone)
                print('phone of {} is changed'.format(username))
            res = "succeed"
        except Exception:
            traceback.print_exc()
        self.write(res)


class updatePasswdHandler(BaseHandler):
    def get(self, username, new_passwd):

        res = "failed"
        try:
            print('change {} passwd'.format(username))
            if new_passwd != "":
                um.changeCtanPW(username, new_passwd)
                res = "succeed"
            else:
                print("new password is empty")
        except Exception as e:
            traceback.print_exc()
        self.write(res)


class resetTimeHandler(BaseHandler):
    def get(self, username):
        res = "failed"
        try:

            print('reset {} start time'.format(username))
            um.resetStartime(username)
            res = "succeed"
        except Exception:
            traceback.print_exc()
        self.write(res)


# 查看用户隐私信息
class privacyInfoHandler(BaseHandler):
    def get(self, username):
        res = ""
        try:

            print('get privacy info for {}'.format(username))
            # 提取用户隐私信息并赋值给res
            res = um.getUserPrivace(username)
        except Exception:
            traceback.print_exc()
        self.write(res)


# 获取左上角信息
class initHandler(BaseHandler):
    def get(self, info_type):
        res = ""
        try:
            if info_type == "get_server_name":
                # 获取服务器名字显示在左上角
                res = machine_name
            elif info_type == "get_attention":
                # 获取用户须知
                # res = "<strong>1.我是用户须知</strong>\n2."
                res = ""
            elif info_type == "modify_title":
                # 修改页面标题（在标签里）
                res = machine_name
        except Exception:
            traceback.print_exc()
        self.write(res)


def main():
    global um, host_name, machine_name
    opts, args = getopt.getopt(sys.argv[1:], "hc:")
    conf_path = None
    for op, value in opts:
        if op == "-c":
            conf_path = value
        if op == "-h":
            help_str = 'python -c bkConfxml.xml Server.py \n' \
                       ' conf_path is the path to config file, default is bkConfxml.xml'
            print(help_str)
            return

    if conf_path is None: conf_path = 'bkConfxml.xml'

    parser = et.parse(conf_path)
    pRoot = parser.getroot()
    machine_name = pRoot.find('machine_name').get('str')
    host_name = pRoot.find('host_name').get('str')
    ls_port = pRoot.find('web_listen_port').get('str')

    um = SRVM('1234567890',  'srvm.dt')

    application = tornado.web.Application([
        (r"/", MainHandler),
        (r"/register/", RegisterHandler),
        (r"/start/(\w+)", startHandler),
        (r"/stop/(\w+)", stopHandler),
        (r"/delete/(\w+)", deleteUserHandler),
        (r"/add/(\w+)/(.*)/(.*)/(.*)/(.*)/(.*)/(.*)", addUserHandler),
        (r"/verify/(\w+)/(.*)", verifyPasswordHandler),
        # gpu
        (r"/status/", GPUStatusHandler),
        (r"/update_status/", updateGPUStatusHandler),
        # res

        (r"/status_cpu/Amax/", AREStatusHandler),
        (r"/status_cpu/Bmax/", BREStatusHandler),
        (r"/status_cpu/Cmax/", CREStatusHandler),
        (r"/status_cpu/Dmax/", DREStatusHandler),
        (r"/status_cpu/Emax/", EREStatusHandler),


        # (r"/update_status_cpu/", updateREStatusHandler),
        (r"/update_status_cpu/Amax", updateAREStatusHandler),
        (r"/update_status_cpu/Bmax", updateBREStatusHandler),
        (r"/update_status_cpu/Cmax", updateCREStatusHandler),
        (r"/update_status_cpu/Dmax", updateDREStatusHandler),
        (r"/update_status_cpu/Emax", updateEREStatusHandler),

        (r"/cpuUtils_main", cpuUtils_MainHandler),
        (r"/cpuUtils_ajax", cpuUtils_AjaxHandler),
        # update data
        (r"/update_mail/(\w+)/(.*)/(.*)/(.*)", updatePrivacyHandler),
        (r"/update_passwd/(\w+)/(.*)", updatePasswdHandler),
        (r"/time_reset/(\w+)", resetTimeHandler),
        (r"/privacy_info/(\w+)", privacyInfoHandler),
        (r"/init/(.*)", initHandler),

    ], **settings)

    # server = tornado.httpserver.HTTPServer(application, ssl_options={
    #     "certfile": os.path.join(os.path.abspath("."), "server.crt"),
    #     "keyfile": os.path.join(os.path.abspath("."), "server.key")
    # })
    # server.listen(str(int(ls_port) + 1))

    application.listen(ls_port)

    print("[Server] Start on %s" % ls_port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == '__main__':
    main()
