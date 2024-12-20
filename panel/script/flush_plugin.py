# coding: utf-8
import sys, os

os.chdir('/www/server/panel/')
sys.path.insert(0, "class/")
import PluginLoader
import public
import time


def clear_hosts():
    """
    @name 清理hosts文件中的bt.cn记录
    @return:
    """
    remove = 0
    try:
        import requests
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

        url = 'https://www.bt.cn/api/ip/info_json'
        res = requests.post(url, verify=False)

        if res.status_code == 404:
            remove = 1
        elif res.status_code == 200 or res.status_code == 400:
            res = res.json()
            if res != "[]":
                remove = 1
    except:
        result = public.ExecShell("curl -sS --connect-timeout 3 -m 60 -k https://www.bt.cn/api/ip/info_json")[0]
        if result != "[]":
            remove = 1

    hosts_file = '/etc/hosts'
    if remove == 1 and os.path.exists(hosts_file):
        public.ExecShell('sed -i "/www.bt.cn/d" /etc/hosts')

def flush_cache():
    '''
        @name 更新缓存
        @author hwliang
        @return void
    '''
    try:
        # start_time = time.time()
        res = PluginLoader.get_plugin_list(1)
        spath = '{}/data/pay_type.json'.format(public.get_panel_path())
        public.downloadFile(public.get_url() + '/install/lib/pay_type.json', spath)
        import plugin_deployment
        plugin_deployment.plugin_deployment().GetCloudList(None)

        # timeout = time.time() - start_time
        if 'ip' in res and res['ip']:
            pass
        else:
            if isinstance(res, dict) and not 'msg' in res: res['msg'] = '连接服务器失败!'
    except:
        pass


def flush_php_order_cache():
    """
    更新软件商店php顺序缓存
    @return:
    """
    spath = '{}/data/php_order.json'.format(public.get_panel_path())
    public.downloadFile(public.get_url() + '/install/lib/php_order.json', spath)


def flush_msg_json():
    """
    @name 更新消息json
    """
    try:
        spath = '{}/data/msg.json'.format(public.get_panel_path())
        public.downloadFile(public.get_url() + '/linux/panel/msg/msg.json', spath)
    except:
        pass


def flush_docker_project_info():
    '''
        @name 更新docker_project版本信息
        @author wzz
        @return void
    '''
    msg = "docker_projcet版本信息"
    try:
        # start_time = time.time()
        res = PluginLoader.get_plugin_list(1)
        config_path = f"{public.get_panel_path()}/config"
        spath = f"{config_path}/docker_project_info.json"
        url = "/install/lib/docker_project/docker_project_info.json"
        public.downloadFile(f"{public.get_url()}{url}", spath)
        import plugin_deployment
        plugin_deployment.plugin_deployment().GetCloudList(None)

        # timeout = time.time() - start_time
        if 'ip' in res and res['ip']:
            pass
        else:
            if isinstance(res, dict) and not 'msg' in res: res['msg'] = '连接服务器失败!'
    except:
        pass


# 2024/3/20 上午 11:09 更新docker_hub镜像排行数据
def flush_docker_hub_repos():
    '''
        @name 更新docker_hub镜像排行数据
        @author wzz <2024/3/20 上午 11:09>
        @param "data":{"参数名":""} <数据类型> 参数描述
        @return dict{"status":True/False,"msg":"提示信息"}
    '''
    public.ExecShell("/www/server/panel/pyenv/bin/python3.7 /www/server/panel/class/btdockerModel/script/syncreposdb.py")


# 2024/5/21 下午5:32 更新 GeoLite2-Country.json
def flush_geoip():

    '''
        @name 检测如果大小小于3M或大于1个月则更新
        @author wzz <2024/5/21 下午5:33>
        @param "data":{"参数名":""} <数据类型> 参数描述
        @return dict{"status":True/False,"msg":"提示信息"}
    '''
    _ips_path = "/www/server/panel/data/firewall/GeoLite2-Country.json"
    m_time_file = "/www/server/panel/data/firewall/geoip_mtime.pl"

    if not os.path.exists(_ips_path):
        os.system("mkdir -p /www/server/panel/data/firewall")
        os.system("touch {}".format(_ips_path))

    try:
        if not os.path.exists(_ips_path):
            public.downloadFile('{}/install/lib/{}'.format(public.get_url(), os.path.basename(_ips_path)), _ips_path)
            public.writeFile(m_time_file, str(int(time.time())))
            return

        _ips_size = os.path.getsize(_ips_path)
        if os.path.exists(m_time_file):
            _ips_mtime = int(public.readFile(m_time_file))
        else:
            _ips_mtime = 0

        if _ips_size < 3145728 or time.time() - _ips_mtime > 2592000:
            os.system("rm -f {}".format(_ips_path))
            os.system("rm -f {}".format(m_time_file))
            public.downloadFile('{}/install/lib/{}'.format(public.get_url(),os.path.basename(_ips_path)), _ips_path)
            public.writeFile(m_time_file, str(int(time.time())))

            if os.path.exists(_ips_path):
                try:
                    import json
                    from xml.etree.ElementTree import ElementTree, Element
                    from safeModel.firewallModel import main as firewall

                    firewallobj = firewall()
                    ips_list = json.loads(public.readFile(_ips_path))
                    if ips_list:
                        for ip_dict in ips_list:
                            if os.path.exists('/usr/bin/apt-get') and not os.path.exists("/etc/redhat-release"):
                                btsh_path = "/etc/ufw/btsh"
                                if not os.path.exists(btsh_path):
                                    os.makedirs(btsh_path)
                                tmp_path = '{}/{}.sh'.format(btsh_path, ip_dict['brief'])
                                if os.path.exists(tmp_path):
                                    public.writeFile(tmp_path, "")

                                _string = "#!/bin/bash\n"
                                for ip in ip_dict['ips']:
                                    if firewallobj.verify_ip(ip):
                                        _string = _string + 'ipset add ' + ip_dict['brief'] + ' ' + ip + '\n'
                                public.writeFile(tmp_path, _string)
                            else:
                                xml_path = "/etc/firewalld/ipsets/{}.xml.old".format(ip_dict['brief'])
                                xml_body = """<?xml version="1.0" encoding="utf-8"?>
<ipset type="hash:net">
  <option name="maxelem" value="1000000"/>
</ipset>
"""
                                if os.path.exists(xml_path):
                                    public.writeFile(xml_path, xml_body)
                                else:
                                    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
                                    public.writeFile(xml_path, xml_body)

                                tree = ElementTree()
                                tree.parse(xml_path)
                                root = tree.getroot()
                                for ip in ip_dict['ips']:
                                    if firewallobj.verify_ip(ip):
                                        entry = Element("entry")
                                        entry.text = ip
                                        root.append(entry)

                                firewallobj.format(root)
                                tree.write(xml_path, 'utf-8', xml_declaration=True)
                except:
                    pass
    except:
        try:
            public.downloadFile('{}/install/lib/{}'.format(public.get_url(), os.path.basename(_ips_path)), _ips_path)
            public.writeFile(m_time_file, str(int(time.time())))
        except:
            pass


if __name__ == '__main__':
    tip_date_tie = '/tmp/.fluah_time'
    if os.path.exists(tip_date_tie):
        last_time = int(public.readFile(tip_date_tie))
        timeout = time.time() - last_time
        if timeout < 600:
            print("执行间隔过短，退出 - {}!".format(timeout))
            sys.exit()
    clear_hosts()
    flush_cache()
    flush_php_order_cache()
    flush_msg_json()
    flush_docker_project_info()
    flush_docker_hub_repos()
    flush_geoip()

    public.writeFile(tip_date_tie, str(int(time.time())))
