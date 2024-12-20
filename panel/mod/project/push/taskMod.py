# coding: utf-8
# -------------------------------------------------------------------
# 宝塔Linux面板
# -------------------------------------------------------------------
# Copyright (c) 2015-2017 宝塔软件(http:#bt.cn) All rights reserved.
# -------------------------------------------------------------------
# Author: baozi <baozi@bt.cn>
# -------------------------------------------------------------------
# 新告警通道管理模块
# ------------------------------
import json
import traceback
import os
from mod.base import json_response

from mod.base.push_mod import PushManager, TaskConfig, TaskRecordConfig, TaskTemplateConfig, PushSystem
from mod.base.push_mod import update_mod_push_system, UPDATE_MOD_PUSH_FILE, load_task_template_by_file, \
    UPDATE_VERSION_FILE
from mod.base.msg import update_mod_push_msg
from mod.base.push_mod.rsync_push import load_rsync_template
from mod.base.push_mod.task_manager_push import load_task_manager_template
from mod.base.push_mod.load_push import load_load_template
from mod.base.push_mod import PUSH_DATA_PATH

def update_mod():
    try:
        with open(UPDATE_VERSION_FILE, 'r') as f:
            if f.read() == "1":
                pl = False
            else:
                pl = True
    except:
        pl = True

    if pl:
        print("========================rewrite=====================")
        load_task_template_by_file("/www/server/panel/mod/base/push_mod/site_push_template.json")
        load_task_template_by_file("/www/server/panel/mod/base/push_mod/system_push_template.json")
        load_task_template_by_file("/www/server/panel/mod/base/push_mod/database_push_template.json")
        load_task_template_by_file("/www/server/panel/mod/base/push_mod/ssl_push_template.json")
        with open(UPDATE_VERSION_FILE, "w") as f:
            f.write("1")

    if not os.path.exists(UPDATE_MOD_PUSH_FILE):
        update_mod_push_msg()

        load_rsync_template()
        load_task_manager_template()
        load_load_template()

        update_mod_push_system()
    CHECK_MOD_PUSH_FILE = "/www/server/panel/data/mod_push_data/check_mod_push_file.pl"
    if not os.path.exists(CHECK_MOD_PUSH_FILE):  
        import sys
        os.chdir('/www/server/panel')
        if not 'class/' in sys.path:
            sys.path.insert(0,'class/')
        import public
        public.ExecShell('nohup btpython /www/server/panel/script/migrate_push_tasks.py > /dev/null 2>&1 &')



update_mod()
del update_mod


class main(PushManager):

    def get_task_list(self, get=None):

        # 通道类型映射，包含模糊匹配规则
        channel_map = {
            "微信公众号": "wx_account",
            "邮箱": "mail",
            "自定义通道": "webhook",
            "飞书": "feishu",
            "钉钉": "dingding",
            "短信": "sms"
        }
        try:
            if get:
                # get["status"] = "false"
                # get["keyword"] = "shylock"
                # 获取状态和关键词参数
                status_filter = get.get("status", None)
                keyword_filter = get.get("keyword", None)
            else:
               status_filter = ""
               keyword_filter =""
            res = TaskConfig().config

            # 按创建时间排序
            res.sort(key=lambda x: x["create_time"])
            # 读取发送者信息
            sender_info = self.get_sender_info()   

            # 根据状态过滤任务
            if status_filter:
                res = [task for task in res if str(task["status"]).lower() == status_filter.lower()]
            
            # 根据关键词过滤任务
            if keyword_filter:
                keyword_filter_lower = keyword_filter.lower()
                filtered_res = []
                for task in res:
                    # print("task",task)
                    task_match = False
                    if keyword_filter_lower=="面板登录时，发出告警":
                        if task['keyword']=="panel_login":
                            task_match = True
                    if keyword_filter_lower in task["title"].lower() or \
                        (task["task_data"].get("title") and keyword_filter_lower in task["task_data"]["title"].lower()) or \
                        keyword_filter_lower in str(task["time_rule"]["send_interval"]) or \
                        keyword_filter_lower in str(task["number_rule"]["day_num"]):
                        task_match = True
                    else:
                        for sender_id in task["sender"]:
                            sender = sender_info.get(sender_id, {})
                            sender_title = sender.get("data", {}).get("title", "").lower()
                            sender_type = sender.get("sender_type", "").lower()
                            if keyword_filter_lower in sender_title or \
                            keyword_filter_lower in sender_type:
                                task_match = True
                                break
                            # 检查关键词是否包含在通道类型的映射键中
                            for chinese_name, channel_type in channel_map.items():
                                if keyword_filter_lower in chinese_name.lower() and channel_type == sender_type:
                                    task_match = True
                                    break
                    if task_match:
                        filtered_res.append(task)
                res = filtered_res
            for i in res:
                i['view_msg'] = self.get_view_msg_format(i)
            
            return json_response(status=True, data=res)
        except:
            import traceback

            print(traceback.format_exc())
            data=[]
            return json_response(status=True, data=res)

    def get_sender_info(self):
        sender_file = '/www/server/panel/data/mod_push_data/sender.json'
        try:
            with open(sender_file, 'r', encoding='utf-8') as f:
                sender_data = json.load(f)
            return {sender['id']: sender for sender in sender_data}
        except Exception as e:
            return {}

    @staticmethod
    def get_task_record(get):
        page = 1
        size = 10
        try:
            if hasattr(get, "page"):
                page = int(get.page.strip())
            if hasattr(get, "size"):
                size = int(get.size.strip())
            task_id = get.task_id.strip()
        except (AttributeError, ValueError, TypeError):
            return json_response(status=False, msg="参数错误")

        t = TaskRecordConfig(task_id)
        t.config.sort(key=lambda x: x["create_time"])
        page = max(page, 1)
        size = max(size, 1)
        count = len(t.config)
        data = t.config[(page - 1) * size: page * size]
        return json_response(status=True, data={
            "count": count,
            "list": data,
        })

    def clear_task_record(self, get):
        try:
            task_id = get.task_id.strip()
        except (AttributeError, ValueError, TypeError):
            return json_response(status=False, msg="参数错误")
        self.clear_task_record_by_task_id(task_id)

        return json_response(status=True, msg="清除成功")

    @staticmethod
    def remove_task_records(get):
        try:
            task_id = get.task_id.strip()
            record_ids = set(json.loads(get.record_ids.strip()))
        except (AttributeError, ValueError, TypeError):
            return json_response(status=False, msg="参数错误")
        task_records = TaskRecordConfig(task_id)
        for i in range(len(task_records.config) - 1, -1, -1):
            if task_records.config[i]["id"] in record_ids:
                del task_records.config[i]

        task_records.save_config()
        return json_response(status=True, msg="清除成功")

    @staticmethod
    def get_task_template_list(get=None):
        res = []
        p_sys = PushSystem()
        for i in TaskTemplateConfig().config:
            if not i['used']:
                continue
            to = p_sys.get_task_object(i["id"], i["load_cls"])
            if not to:
                continue
            t = to.filter_template(i["template"])
            if not t:
                continue
            i["template"] = t
            res.append(i)

        return json_response(status=True, data=res)

    @staticmethod
    def get_view_msg_format(task: dict) -> str:
        from mod.base.push_mod.rsync_push import ViewMsgFormat as Rv
        from mod.base.push_mod.site_push import ViewMsgFormat as Sv
        from mod.base.push_mod.task_manager_push import ViewMsgFormat as Tv
        from mod.base.push_mod.database_push import ViewMsgFormat as Dv
        from mod.base.push_mod.system_push import ViewMsgFormat as SSv
        from mod.base.push_mod.load_push import ViewMsgFormat as Lv
        from mod.base.push_mod.ssl_push import ViewMsgFormat as SSLv

        list_obj = [Rv(), Sv(), Tv(), Dv(), SSv(), Lv(), SSLv()]
        for i in list_obj:
            res = i.get_msg(task)
            if res is not None:
                return res
        return '<span>--</span>'
