import json
import os
import sys
from datetime import datetime

if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")

os.chdir("/www/server/panel")
import public

class SSHbase():
    def __init__(self):
        super().__init__()

    @staticmethod
    def return_area(result, key):
        """
        @name 格式化返回带IP归属地的数组
        @param result<list> 数据数组
        @param key<str> ip所在字段
        @return list
        """
        tmps = []
        for data in result:
            tmps.append(data[key])

        res = {}
        for t in tmps:
            if public.is_ipv6(t):continue
            ip_area = public.get_ip_location(t)
            if not ip_area:
                ip_area = {"info": "未知地区"}

            ip_area = ip_area.raw
            country = ip_area.get("country", {})
            ip_area["info"] = country.get("country", "未知") + " " + country.get("province", "未知") + " " + country.get("city", "未知") if country else "未知地区"
            res[t] = ip_area

        for data in result:
            if data[key] in res:
                data['area'] = res[data[key]] if not "127.0.0" in data[key] else {"info": "本机地址(例如左侧终端)"}
        return result
    @staticmethod
    def journalctl_system():
        try:
            if os.path.exists('/etc/os-release'):
                f = public.readFile('/etc/os-release')
                f = f.split('\n')
                ID = ''
                VERSION_ID = 0
                for line in f:
                    if line.startswith('VERSION_ID'):
                        VERSION_ID = int(line.split('=')[1].split('.')[0].strip('"'))
                    if line.startswith('ID'):
                        if ID != '': continue
                        ID = line.strip().split('=')[1].strip('"')
                        try:
                            ID = ID.split('.')[0]
                        except:
                            pass
                if (ID.lower() == 'debian' and VERSION_ID >= 11) or (ID.lower() == 'ubuntu' and VERSION_ID >= 20):
                    return True
                return False
        except:
            return False

    @staticmethod
    def parse_login_entry(parts, year):
        """解析登录条目"""
        try:
            # 判断日志格式类型
            if 'T' in parts[0]:  # centos7以外的格式
                # 解析ISO格式时间戳
                dt = datetime.fromisoformat(parts[0].replace('Z', '+00:00'))
                user_index = parts.index('user') + 1 if 'user' in parts else parts.index('for') + 1
                ip_index = parts.index('from') + 1
                port_index = parts.index('port') + 1 if 'port' in parts else -1
            else:
                # 解析传统格式时间
                month = parts[0]
                day = parts[1]
                time_str = parts[2]
                # 如果月份大于当前月，说明年份不对，直接把year修改成1970年
                if datetime.strptime("{} {}".format(month, day), "%b %d").month > datetime.now().month:
                    year = "1970"
                dt_str = "{} {} {} {}".format(month, day, year, time_str)
                dt = datetime.strptime(dt_str, "%b %d %Y %H:%M:%S")
                user_index = parts.index('for') + 1  if "invalid" not in parts else -6
                ip_index = parts.index('from') + 1
                port_index = parts.index('port') + 1 if 'port' in parts else -1

            entry = {
                "timestamp": int(dt.timestamp()),
                "time": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "type": "success" if ("Accepted" in parts) else "failed",
                "status": 1 if ("Accepted" in parts) else 0,
                "user": parts[user_index],
                "address": parts[ip_index],
                "port": parts[port_index] if port_index != -1 else "",
                "deny_status": 0,
                "login_type": "publickey" if "publickey" in parts else "password"  # 添加登录类型
            }
            return entry
        except Exception as e:
            public.print_log(public.get_error_info())
            return None
