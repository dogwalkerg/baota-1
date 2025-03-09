import json
import os
import sys
import time
from datetime import datetime

if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")

os.chdir("/www/server/panel")
import public
# from mod.project.ssh.base import SSHbase
from mod.project.ssh.journalctlMod import JournalctlManage
from mod.project.ssh.secureMod import SecureManage


class main(JournalctlManage, SecureManage):

    def __init__(self):
        super(main).__init__()

    def get_ssh_list(self, get):
        """
        @name 获取日志列表
        @param data:{"p":1,"limit":20,"search":"","select":"ALL"}
        @return list
        """
        # 缓存文件路径
        cache_file = 'data/ssh_login_history.json'

        # 读取IP封禁规则
        ip_rules_file = "data/ssh_deny_ip_rules.json"
        try:
            ip_rules = json.loads(public.readFile(ip_rules_file))
        except Exception:
            ip_rules = []

        # 读取缓存的历史数据
        try:
            if os.path.exists(cache_file):
                cached_data = json.loads(public.readFile(cache_file))
                cached_logins = cached_data.get('logins', [])
                # 记录每个文件的最后处理位置
                file_positions = cached_data.get('file_positions', {})
            else:
                cached_logins = []
                file_positions = {}
        except Exception as e:
            cached_logins = []
            file_positions = {}

        # 根据系统选择日志处理方式，并获取新日志
        new_logins, current_positions = self.get_journalctl_logs(file_positions) if self.journalctl_system() else self.get_secure_logs(file_positions)

        # 合并新旧数据并去重
        all_logins = cached_logins + new_logins
        # 去重
        unique_logins = []
        seen = set()
        for log in all_logins:
            key = (log["timestamp"], log["address"], log["user"], log["type"])
            log["deny_status"] = 1 if log["address"] in ip_rules else 0
            if key not in seen:
                seen.add(key)
                unique_logins.append(log)

        # 更新缓存文件
        try:
            cache_data = {
                'last_update': int(time.time()),
                'logins': unique_logins,
                'file_positions': current_positions
            }
            public.writeFile(cache_file, json.dumps(cache_data))
        except Exception as e:
            pass

        get.select = get.get("select", "ALL")
        if get.select == "Failed":
            unique_logins = [log for log in unique_logins if log["status"] == 0]
        elif get.select == "Accepted":
            unique_logins = [log for log in unique_logins if log["status"] == 1]

        # 关键字搜索 ip or user
        keyword = get.get("search", "").strip().lower()
        if keyword:
            unique_logins = [log for log in unique_logins if
                             keyword in log["address"].lower() or keyword in log["user"].lower()]

        # 按时间戳排序
        unique_logins.sort(key=lambda x: x["timestamp"], reverse=True)

        # 处理分页
        get.get_all = get.get("get_all", 0)
        if int(get.get_all) == 1:
            return unique_logins

        try:
            # 获取分页参数
            page = int(get.p) if hasattr(get, 'p') else 1
            limit = int(get.limit) if hasattr(get, 'limit') else 20

            # 计算起始和结束位置
            start = (page - 1) * limit
            end = start + limit

            unique_logins = self.return_area(unique_logins[start:end], 'address')
        except Exception as e:
            return public.returnMsg(False, "分页处理失败: {}".format(str(e)))
        unique_logins = self.return_area(unique_logins[:20], 'address')

        return unique_logins

    def get_ssh_intrusion(self, get):
        """
        @name 登陆详情统计  周期 昨天/今天  类型 成功/失败
        @return {"error": 0, "success": 0, "today_error": 0, "today_success": 0}
        """
        try:
            # 获取并更新日志数据
            get.get_all = 1
            all_logins = self.get_ssh_list(get)

            # 获取今天开始的时间戳
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_timestamp = int(today.timestamp())

            # 初始化计数器
            stats = {
                'error': 0,
                'success': 0,
                'today_error': 0,
                'today_success': 0
            }

            # 统计数据
            for login in all_logins:
                if login['status'] == 1:
                    stats['success'] += 1
                    if login['timestamp'] >= today_timestamp:
                        stats['today_success'] += 1
                else:
                    stats['error'] += 1
                    if login['timestamp'] >= today_timestamp:
                        stats['today_error'] += 1

            return stats

        except Exception as e:
            import traceback
            return {
                'error': 0,
                'success': 0,
                'today_error': 0,
                'today_success': 0
            }

    def index_ssh_info(self, get):
        """
        获取今天和昨天的SSH登录统计
        @return: list [今天登录次数, 昨天登录次数]
        """
        from datetime import datetime, timedelta

        today_count = 0
        yesterday_count = 0

        try:
            # 获取并更新日志数据
            get.get_all = 1
            all_logins = self.get_ssh_list(get)

            # 获取今天和昨天的开始时间戳
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday = today - timedelta(days=1)
            today_timestamp = int(today.timestamp())
            yesterday_timestamp = int(yesterday.timestamp())

            # 遍历登录记录进行统计
            for login in all_logins:
                timestamp = login['timestamp']

                # 统计今天的数据
                if timestamp >= today_timestamp:
                    today_count += 1
                # 统计昨天的数据
                elif yesterday_timestamp <= timestamp < today_timestamp:
                    yesterday_count += 1
                # 早于昨天的数据不需要统计
                elif timestamp < yesterday_timestamp:
                    break  # 因为数据是按时间戳倒序的，可以直接跳出循环

            return [today_count, yesterday_count]
        except Exception as e:
            import traceback
            public.print_log(f"统计SSH登录信息失败: {traceback.format_exc()}")
            return [0, 0]
