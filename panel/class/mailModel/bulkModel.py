# -*- coding: utf-8 -*-
# 批量发邮件

import re, json, os, sys, time, socket, requests
# import datetime
from dateutil.parser import parse

if sys.version_info[0] == 3:
    from importlib import reload

import public
sys.path.append(public.get_plugin_path()+'/mail_sys')


try:
    import dns.resolver
except:
    if os.path.exists('/www/server/panel/pyenv'):
        public.ExecShell('/www/server/panel/pyenv/bin/pip install dnspython')
    else:
        public.ExecShell('pip install dnspython')
    import dns.resolver
from mailModel.base import Base
from mail_sys_main import SendMail
import math
try:
    import jwt
except:
    public.ExecShell('btpip install pyjwt')
    import jwt
from datetime import datetime, timedelta

# 有问题先不用
class main_bak(Base):

    def __init__(self):
        super().__init__()
        self.in_bulk_path = '/www/server/panel/data/mail/in_bulk'
        if not os.path.exists(self.in_bulk_path):
            os.mkdir(self.in_bulk_path)
        # 新增3个表  批量发件用
        # 邮件模版表
        sql1 = '''CREATE TABLE IF NOT EXISTS `temp_email` (
          `id` INTEGER  PRIMARY KEY AUTOINCREMENT,        
          `name` varchar(255) NULL,         -- 邮件名 有模版时为模版名
          `addresser` varchar(320) NULL,    -- 发件人
          `recipient` text NOT NULL,        -- 收件人路径
          `subtype` varchar(255) NOT NULL,  -- 邮件类型  ['plain', 'html']  
          `subject` text NOT NULL,          -- 邮件主题
          `content` text NOT NULL,          -- 邮件正文 路径
          `created` INTEGER NOT NULL,  
          `modified` INTEGER NOT NULL,
          `is_temp` tinyint(1) NOT NULL DEFAULT 0  -- 是否是模版
          );'''
        self.M('').execute(sql1, ())

        # 任务表
        sql2 = '''CREATE TABLE IF NOT EXISTS `email_task` (
          `id` INTEGER  PRIMARY KEY AUTOINCREMENT,    
          `task_name` varchar(255) NOT NULL,        -- 任务名
          `addresser` varchar(320) NOT NULL,        -- 发件人
          `recipient_count` int NOT NULL,           -- 收件人数量
          `task_process` tinyint NOT NULL,     -- 任务进程  0待执行   1执行中  2 已完成
          `pause` tinyint NOT NULL,      -- 暂停状态  1 暂停中     0 未暂停     执行中的任务才能暂停
          `temp_id` INTEGER NOT NULL,          -- 邮件对应id
          `is_record` INTEGER NOT NULL DEFAULT 0,        -- 是否记录到发件箱
          `unsubscribe` INTEGER NOT NULL DEFAULT 0,      -- 是否增加退订按钮   0 没有   1 增加退订按钮
          `threads` INTEGER NOT NULL DEFAULT 0,          -- 线程数量 控制发送线程数 0时自动控制线程   0~10
          `created` INTEGER NOT NULL,
          `modified` INTEGER NOT NULL,
          `active` tinyint(1) NOT NULL DEFAULT 0    --  预留字段
          );'''
        self.M('').execute(sql2, ())

        # 发送统计表 改 错误详情表

        sql3 = '''CREATE TABLE IF NOT EXISTS `task_count` (
          `id` INTEGER  PRIMARY KEY AUTOINCREMENT,    
          `task_id` INTEGER NOT NULL,                   -- 所属任务编号
          `recipient` varchar(320) NOT NULL,            -- 收件人
          `delay` varchar(320) NOT NULL,            -- 延时
          `delays` varchar(320) NOT NULL,            -- 各阶段延时
          `dsn` varchar(320) NOT NULL,            -- dsn
          `relay` text NOT NULL,            -- 中继服务器
          `domain` varchar(320) NOT NULL,               -- 域名
          `status` varchar(255) NOT NULL,               -- 错误状态
          `err_info` text NOT NULL                      -- 错误详情
          );'''
        self.M('').execute(sql3, ())

    def check_task_status(self, args):
        '''
        执行发送邮件的定都任务
        :param
        :return:
        '''
        try:
            print("|-准备执行发送任务")
            # public.print_log("执行发送任务")
            # task_process  0待执行   1执行中  2 已完成
            task_info = self.M('email_task').order('created desc').find()
            # 没任务
            if not task_info or not isinstance(task_info, dict):
                print("|-没有任务")
                # public.print_log("|-没任务")
                return False
            # 非执行中(暂停了)
            if task_info['task_process'] != 1:
                print("|-无需执行")
                # public.print_log("|-等待执行或任务已完成 ")
                return False

            start_mark = '/www/server/panel/plugin/mail_sys/start_Task.pl'
            start_send = '/www/server/panel/plugin/mail_sys/start_Send.pl'
            end_mark = '/www/server/panel/plugin/mail_sys/end_Task.pl'
            # 查看任务是否已开始
            if os.path.exists(start_mark):
                # 新的一天
                # public.print_log("|-执行一天后 {}".format(int(public.readFile(start_mark)) + 86400))
                # public.print_log("|-当前 {}".format(int(time.time())))
                if int(public.readFile(start_mark)) + 86400 < int(time.time()):
                    # public.print_log("|-时间未超出 清掉当天配额")
                    # 重置时间
                    timestamp = int(time.time())
                    public.writeFile(start_mark, str(timestamp))
                    # 清空统计
                    count_sent = '/www/server/panel/plugin/mail_sys/count_sent_domain.json'
                    os.remove(count_sent)
                # 当天 已经开始过 跳过
                else:
                    print("|-当天的执行配额已用完")
                    # public.print_log("|-当天发过")
                    return False
            else:
                timestamp = str(int(time.time()))
                public.writeFile(start_mark, timestamp)
                # 记录发送时间  后续不能改
                public.writeFile(start_send, str(timestamp))

            # 邮件相关内容
            email_info = self.M('temp_email').where('id=?', task_info['temp_id']).find()
            # 处理后的收件人文件
            recipient_path = email_info['recipient']
            addresser = email_info['addresser']
            subject = email_info['subject']
            content_path = email_info['content']
            subtype = email_info['subtype']

            try:
                content_detail = public.readFile(content_path)
                content_detail = json.loads(content_detail)
            except:
                # 直接上传的文件不用
                content_detail = public.readFile(content_path)

            unsubscribe = task_info['unsubscribe']
            # unsubscribe = 1
            threads = task_info['threads']

            # 检查html
            if subtype.lower() == 'html':
                content_detail = '<html>' + content_detail + '</html>'

            # 收件人
            recipient_analysis = {}
            try:
                data = public.readFile(recipient_path)
                recipient_analysis = json.loads(data)
            except:
                public.print_log(public.get_error_info())
                # return public.returnMsg(False, 'Abnormal or malformed file contents')

            # 发件人
            data = self.M('mailbox').where('username=?', addresser).field('password_encode,full_name').find()
            password = self._decode(data['password_encode'])
            # public.print_log("批量发件1  用户信息  {}--({})".format(addresser, password))
            full_name = data['full_name']
            # 反向dns
            # is_ptr = self._get_ptr_record(None)
            _, domain_ = addresser.split('@')
            is_ptr = self._check_ptr_domain(domain_)
            # is_ptr = True
            # public.print_log("批量发件1  反向dns {}".format(is_ptr))
            # import subprocess
            # import multiprocessing
            other_today = {
                'gmail.com': {"count": 0, "info": []},
                'googlemail.com': {"count": 0, "info": []},
                'hotmail.com': {"count": 0, "info": []},
                'outlook.com': {"count": 0, "info": []},
                'yahoo.com': {"count": 0, "info": []},
                'icloud.com': {"count": 0, "info": []},
                'other': {"count": 0, "info": []},
            }
            # 添加开始标记  邮件发送时间比记录靠前
            # timestamp = int(time.time())
            # public.writeFile(start_mark, str(timestamp))
            # public.writeFile(start_send, str(timestamp))
            # 批量发件的内容是否要保存到发件箱  0不保存  1保存
            is_record = task_info['is_record']

            # 记录所有线程
            p_list = []
            # (查看反向dns
            if not is_ptr:
                # 今日能发送的
                send_today = {
                    'gmail.com': {"count": 0, "info": []},
                    'googlemail.com': {"count": 0, "info": []},
                    'hotmail.com': {"count": 0, "info": []},
                    'outlook.com': {"count": 0, "info": []},
                    'yahoo.com': {"count": 0, "info": []},
                    'icloud.com': {"count": 0, "info": []},
                    'other': {"count": 0, "info": []},
                }
                # 循环调用发件
                for domain, details in recipient_analysis.items():
                    today_count = 0
                    # 查看当前domain已发送数量
                    count = self._get_count_limit(domain)
                    # public.print_log(" 查看当前domain是否有发送额度--{}".format(count))
                    # 无发送额度
                    if count > 5000:
                        # 记录未发送状态 第二天发送
                        today_count = 0
                    # 需要发送的+已发送>额度
                    if details['count'] + count > 5000:
                        # 当日可发送数量  额度-已发送  5-3=2   有3
                        today_count = 5000 - count
                        # today_count = 5000 - count - details['count']
                    else:
                        today_count = 5000

                    if today_count != 0:
                        if details['count'] < today_count:
                            send_today[domain] = details
                            other_today[domain] = {"count": 0, "info": []}
                        else:
                            send_today[domain] = {"count": len(details[:today_count]), "info": details[:today_count]}  # 取前n个元素
                            other_today[domain] = {"count": len(details[today_count:]), "info": details[today_count:]}
                    else:
                        send_today[domain] = {"count": 0, "info": []}
                        other_today[domain] = details

                # public.print_log("批量发件1  准备发件 无ptr--{}".format(send_today))
                try:
                    for domain, detail in send_today.items():
                        # public.print_log(" 无ptr 循环发送--{}".format(detail))
                        # self._send_email_all(detail, addresser, password, full_name, subject, content_detail, subtype,
                        #                  is_record)
                        if unsubscribe:
                            p = self.run_thread(self._send_email_all_unsubscribe,
                                                (detail, addresser, password, full_name, subject, content_detail,
                                                 subtype, is_record))
                        else:
                            p = self.run_thread(self._send_email_all,
                                                (detail, addresser, password, full_name, subject, content_detail,
                                                 subtype, is_record))
                        p_list.append(p)
                except Exception as ex:
                    public.print_log(public.get_error_info())
                    public.print_log("分批发送 - error: {}".format(ex))
                    # 删除开始标志
                    if os.path.exists(start_mark):
                        os.remove(start_mark)
                    print("|-分批发送失败 - error: {}".format(ex))
                    # public.print_log("|-分期交货失败 - error: {}".format(ex))
                    return False

                # 更新今天发送后的
                public.writeFile(recipient_path, json.dumps(other_today))
            else:
                # public.print_log("准备发件2  全部发送")
                try:
                    import random

                    listall = []
                    for domain, detail in recipient_analysis.items():
                        listall += detail['info']

                    # 打乱每个列表
                    random.shuffle(listall)

                    # 根据数量 选线程数  根据订阅与否 选订阅发送方式

                    if len(listall) > 5000:
                    # if len(listall) > 50:
                        # 单独调用 只修改1处
                        # public.print_log("分批发送 分线程")

                        p1_list = self.send_emails_split(listall, addresser, password, full_name, subject, content_detail,
                                                         subtype,
                                                         is_record, unsubscribe, threads)
                        p_list.extend(p1_list)

                    else:
                        # _send_email_all多处使用
                        recipients = {"count": len(listall), "info": listall}
                        if unsubscribe:

                            p = self.run_thread(self._send_email_all_unsubscribe,
                                                (recipients, addresser, password, full_name, subject, content_detail,
                                                 subtype, is_record))
                        else:
                            p = self.run_thread(self._send_email_all,
                                                (recipients, addresser, password, full_name, subject, content_detail,
                                                 subtype, is_record))
                        p_list.append(p)

                    # 清空收件人记录
                    public.writeFile(recipient_path, json.dumps(other_today))
                except Exception as ex:
                    public.print_log(public.get_error_info())
                    public.print_log("发送 - error: {}".format(ex))
                    # 删除开始标志
                    if os.path.exists(start_mark):
                        os.remove(start_mark)
                    print("发送失败 - error: {}".format(ex))
                    public.print_log("发送失败 - error: {}".format(ex))
                    return False

            # public.print_log("等线程")
            # 等线程结束
            for p in p_list:
                p.join()

            # 添加结束标记  当收件人文件列表为空 说明发完
            other_todays = {}
            try:
                data = public.readFile(recipient_path)
                other_todays = json.loads(data)
            except:
                public.print_log(public.get_error_info())

            if all(value['count'] == 0 for value in other_todays.values()):
                timestamp = int(time.time()) + 60
                public.writeFile(end_mark, str(timestamp))
                # 任务状态改已完成
                self.M('email_task').where('id=?', task_info['id']).update({'task_process': 2})
                # public.print_log("发完了 收工")
            return public.returnMsg(True, '已完成发送任务')
        except:
            public.print_log(public.get_error_info())



    # 大批量邮件拆分发送  订阅 分线程
    def send_emails_split(self, listall, addresser, password, full_name, subject, content_detail, subtype, is_record, unsubscribe, threads):
        # info = detail["info"]
        total_recipients = len(listall)
        # max_batches = 3  # 指定最大循环次数
        max_batches = int(threads)
        if max_batches == 0:
            # 根据数量定  大于50000  5线程    否则3线程
            if total_recipients > 50000:
                max_batches = 5
            else:
                max_batches = 3

        # # 订阅 线程翻倍
        # if unsubscribe:
        #     max_batches = max_batches*2


        # 计算每个线程要发送的数量
        batch_size = math.ceil(total_recipients / max_batches)

        num_batches = math.ceil(total_recipients / batch_size)
        # public.print_log("batch_size--每个线程要发{}, num_batches--线程数{}".format(batch_size,num_batches))
        p_all = []

        for i in range(num_batches):
            start_idx = i * batch_size
            end_idx = min(total_recipients, (i + 1) * batch_size)
            batch_recipients = listall[start_idx:end_idx]
            # public.print_log("分批发 线程--{}".format(len(batch_recipients)))
            # 用线程发邮件
            recipients = {"count": len(batch_recipients), "info": batch_recipients}
            # 判断订阅
            if unsubscribe:
                # 如果是订阅 线程翻倍
                p = self.run_thread(self._send_email_all_unsubscribe,
                                (recipients, addresser, password, full_name, subject, content_detail,
                                 subtype, is_record))
            else:
                p = self.run_thread(self._send_email_all,
                                (recipients, addresser, password, full_name, subject, content_detail,
                                 subtype, is_record))
            p_all.append(p)

        return p_all



    def run_thread(self,fun, args=(), daemon=False):
        '''
            @name 使用线程执行指定方法
            @author hwliang<2020-10-27>
            @param fun {def} 函数对像
            @param args {tuple} 参数元组
            @param daemon {bool} 是否守护线程
            @return 线程
        '''
        import threading
        p = threading.Thread(target=fun, args=args)
        p.setDaemon(daemon)
        p.start()
        return p


    # 只根据上次时间和当前时间筛选日志  无上次时间 取开始时间
    def check_task_finish(self, args=None):
        '''
        发送完毕后处理发送失败的日志
        :param
        :return:
        '''

        # public.print_log("进入处理日志")
        start_send = '/www/server/panel/plugin/mail_sys/start_Send.pl'  # 只记录任务开始时间  取日志记录 不更新
        start_mark = '/www/server/panel/plugin/mail_sys/start_Task.pl'  # 用于每日额度记录 每天更新时间
        end_mark = '/www/server/panel/plugin/mail_sys/end_Task.pl'
        # 上一次取日志的时间
        last_time = '/www/server/panel/plugin/mail_sys/last_Time.pl'
        task_info = self.M('email_task').order('created desc').find()
        # 没有任务
        if not task_info:
            print("|- 没有任务")
            # public.print_log("没有任务")
            return False


        # # 没有开始任务标记 (1 未开始   2 处理完毕)
        # if not os.path.exists(start_mark):
        #     print("|- There are no tasks to work on")
        #     return False

        # 没有开始任务标记 (1 未开始   2 处理完毕)
        if not os.path.exists(start_send):
            print("|- 没有开始任务标记")
            # public.print_log("没有开始任务标记")
            return False



        # 任务结束状态2
        if task_info['task_process'] != 0:  # (0 是待执行  执行中和结束的都可以扫)
            # 任务结束状态 + 无 去处理标记 = 处理过 退出
            # if not os.path.exists(end_mark):
            #     print("|- Tasks that have not been sent out")
            #     return False

            # 任务结束状态 + 有 去处理标记 = 去处理
            # 日志,  改统计,  删 去处理标记
            # else:
            # 取日志开始时间
            last_timestamp = int(time.time())
            start = int(public.readFile(start_send))
            # 上次处理时间 没有就用开始时间
            if os.path.exists(last_time):
                # print("|- There are no tasks to work on")
                # public.print_log("有上次处理时间")
                start = int(public.readFile(last_time))
            if start == '0':
                start = int(public.readFile(start_mark))

            # 取结束时间
            end = int(time.time())
            if os.path.exists(end_mark):
                # public.print_log("|- 有任务结束标记")
                end = int(public.readFile(end_mark))


            task_id = task_info['id']
            task_name = task_info['task_name']
            # 错误日志路径
            error_log = "/www/server/panel/data/mail/in_bulk/errlog/{}_{}.log".format(task_name, task_id)

            print("|-过滤日志区间: start {} --> End {}".format(start, end))
            public.print_log("|-开始分析: start {} --> End {}".format(start, end))
            # 分析日志并记录
            self._mail_error_log(start, end, error_log, task_id)
            print("|-日志记录完成")
            # 更新上次记录时间
            public.writeFile(last_time, str(last_timestamp))

            # 任务已结束 最后一次扫描
            if task_info['task_process'] == 2:
                # 删标记
                if os.path.exists(end_mark):
                    os.remove(end_mark)
                if os.path.exists(last_time):
                    os.remove(last_time)
                if os.path.exists(start_send):
                    os.remove(start_send)
                if os.path.exists(start_mark):
                    os.remove(start_mark)

            print("|- 已移除任务结束标记")
            # public.print_log("|- 分析完")
            return True
        # 未执行任务不用处理
        else:
            print("|-未执行的任务不用处理")
            # public.print_log("|- 任务还没执行  不能处理")
            return False

    def _read_recipient_file(self,file_path):

        if file_path.endswith('.json'):
            try:
                emails = json.loads(public.readFile(file_path))
                return emails, None
            except Exception as e:
                return None, f'从文件读取json内容失败: {e}'
        else:
            try:
                with open(file_path, 'r') as file:
                    emails = file.read().splitlines()
                return emails, None
            except Exception as e:
                return None, f'从文件读取文本内容失败: {e}'

    # 导入收件人
    def processing_recipient(self, args):
        '''
        导入收件人
        :param  file
        :return:
        '''
        args.file = args.get('file/s', '')

        if not os.path.exists("{}/recipient".format(self.in_bulk_path)):
            os.mkdir("{}/recipient".format(self.in_bulk_path))
        file_path = "{}/recipient/{}".format(self.in_bulk_path, args.file)

        if not args.file:
            return public.returnMsg(False, '参数错误')

        if not os.path.exists(file_path):
            return public.returnMsg(False, '文件不存在')
        emails = []
        # 判断file_path 文件格式  txt  json  txt: 一行一个   json:["1","2",...]
        try:
            emails, err = self._read_recipient_file(file_path)
            # public.print_log("获取文件内容 ---{}    type:{}".format(emails, type(emails)))
            if err:
                return public.returnMsg(False, err)
            # 去除空内容
            emails = list(filter(lambda x: x != "", emails))
        except Exception as e:
            public.print_log(public.get_error_info())
            return public.returnMsg(False, e)
        # public.print_log("获取文件内容 55---{}".format(emails))

        # recipient_analysis = {
            # 'gmail.com': {"count": 0, "info": []},
            # 'googlemail.com': {"count": 0, "info": []},
            #
            # 'hotmail.com': {"count": 0, "info": []},
            # 'outlook.com': {"count": 0, "info": []},
            #
            # 'yahoo.com': {"count": 0, "info": []},
            #
            # 'icloud.com': {"count": 0, "info": []},
            #
            # 'other': {"count": 0, "info": []},

            # 'protonmail.com': {"count": 0, "info": []},
            # 'zoho.com': {"count": 0, "info": []},

        # }
        recipient_analysis = {}

        verify_results = {"success": {}, "failed": {}}

        for email in emails:
            validation_result = self._check_email_address(email)
            if not validation_result:
                verify_results["failed"][email] = '电子邮件地址格式不正确!'
                continue
            if any(char.isupper() for char in email):
                verify_results["failed"][email] = '电子邮件地址不能包含大写字母!'
                continue

            local_part, domain = email.lower().split('@')
            domain_key = domain
            if not recipient_analysis.get(domain_key):
                recipient_analysis[domain_key] = {"count": 0, "info": []}
            recipient_analysis[domain_key]["info"].append(email)
            recipient_analysis[domain_key]["count"] += 1
            verify_results["success"][email] = "Common post office" if domain != 'other' else "Other domains"

        # 处理后的数据写入新文件
        recipient_path = "{}/recipient/verify_{}".format(self.in_bulk_path, args.file)
        # public.print_log("写入文件路径--- {}".format(recipient_path))
        public.writeFile(recipient_path, public.GetJson(recipient_analysis))

        # 统计总数 写入文件
        # recipient_count_path = "{}/recipient/recipient_count".format(self.in_bulk_path)
        recipient_count_path = "/www/server/panel/plugin/mail_sys/recipient_count"
        # 累计recipient_analysis所有count数量
        total_count = sum(domain_data["count"] for domain_data in recipient_analysis.values())
        public.writeFile(recipient_count_path, str(total_count))

        return public.returnMsg(True, '导入成功')

    # 获取收件人处理数据 添加时展示
    def get_recipient_data(self, args):
        '''
        获取发送预计完成时间
        :param  file
        :return:
        '''
        if not args.file:
            return public.returnMsg(False, '参数错误')
        recipient_path = "{}/recipient/verify_{}".format(self.in_bulk_path, args.file)
        try:
            data = public.readFile(recipient_path)
            recipient_analysis = json.loads(data)
        except Exception as e:
            public.print_log(public.get_error_info())
            return public.returnMsg(False, '文件内容异常或格式错误: {}'.format(e))

        return public.returnMsg(True, recipient_analysis)
        # # 定义要累加的域名组
        # domain_groups = {
        #     'gmail_group': ['gmail.com', 'googlemail.com'],
        #     'outlook_group': ['hotmail.com', 'outlook.com'],
        # }
        #
        # # 初始化计数器
        # counts = {group: 0 for group in domain_groups.keys()}
        #
        # # 累加特定域名组的计数
        # for domain, details in recipient_analysis.items():
        #     for group, domains in domain_groups.items():
        #         if domain in domains:
        #             counts[group] += details["count"]
        #
        # # 获取累加结果
        # gmail_count = counts['gmail_group']
        # outlook_count = counts['outlook_group']
        #
        # yahoo_count = recipient_analysis['yahoo.com']["count"]
        # icloud_count = recipient_analysis['icloud.com']["count"]
        # outher_count = recipient_analysis['other']["count"]
        #
        # # 查看反向解析设置状态
        # if self._get_ptr_record():
        #     gmail_etc = 1
        #     outlook_etc = 1
        #     yahoo_etc = 1
        #     icloud_etc = 1
        #     outher_etc = 1
        # else:
        #     # 获取预计完成时间
        #     gmail_etc = math.ceil(gmail_count / 4900)
        #     outlook_etc = math.ceil(outlook_count / 4900)
        #     yahoo_etc = math.ceil(yahoo_count / 4900)
        #     icloud_etc = math.ceil(icloud_count / 4900)
        #     # 非指定域名不限制
        #     outher_etc = 1
        #
        # data = {
        #     'gmail': {"count": gmail_count, "etc": gmail_etc},
        #     'outlook': {"count": outlook_count, "etc": outlook_etc},
        #     'yahoo.com': {"count": yahoo_count, "etc": yahoo_etc},
        #     'icloud.com': {"count": icloud_count, "etc": icloud_etc},
        #     'other': {"count": outher_count, "etc": outher_etc},
        # }
        #
        # return public.returnMsg(True, data)

    # 添加批量发送任务  需要生成邮件id  任务id  创建任务统计  已增加新字段 线程和退订
    def add_task(self, args):
        '''
        添加批量发送任务
        :param args:
        :return:
        '''

        # 判断参数传递
        # 必传  addresser  subject content      任务 :  task_name  addresser   task_process(立即执行 1   稍后执行 0)
        # 选传  is_temp 是否是模版  file_content= '邮件正文(1)' 邮件内容上传名称  file_recipient='收件人11' 收件人上传名称  subtype 邮件类型
        # 指定邮件内容上传到 /www/server/panel/data/mail/in_bulk/content/
        # 指定收件人上传到 /www/server/panel/data/mail/in_bulk/recipient/
        # 新增 退订按钮
        # 新增 线程数

        try:
            if not hasattr(args, 'addresser') or args.get('addresser/s', '') == '':
                return public.returnMsg(False, 'Parameter error')
            # if not hasattr(args, 'subject') or args.get('subject/s', '') == '':
                # return public.returnMsg(False, 'Parameter error')
            if not hasattr(args, 'task_name') or args.get('task_name/s', '') == '':
                return public.returnMsg(False, 'Parameter error')

            # 添加前先检查是否有正在执行或未执行的任务  task_process  0待执行   1执行中  2 已完成
            task_info = self.M('email_task').order('created desc').find()
            if task_info and task_info['task_process'] != 2:
                return public.returnMsg(False, '请先处理未完成的任务')

            task_name = args.get('task_name/s', '')
            count = self.M('email_task').where('task_name=?', task_name).count()
            if count:
                return public.returnMsg(False, '任务名已存在')
            # 是否记录到发件箱
            if not hasattr(args, 'is_record') or args.get('is_record/d', 0) == 0:
                is_record = 0
            else:
                is_record = 1
            # 是否增加退订 unsubscribe
            if not hasattr(args, 'unsubscribe') or args.get('unsubscribe/d', 0) == 0:
                unsubscribe = 0
            else:
                unsubscribe = 1
            # 线程数
            if not hasattr(args, 'threads') or args.get('threads/d', 0) == 0:
                threads = 0
            else:
                threads = int(args.threads)
                if threads > 10:
                    return public.returnMsg(False, '线程数不能超过10')


            # 邮件类型检查
            subtype = args.subtype if 'subtype' in args else 'html'
            if subtype.lower() not in ['plain', 'html']:
                return public.returnMsg(False, '错误的邮件类型')

            # 判断是否是上传邮件
            if not hasattr(args, 'up_content'):
                args.up_content = 0

            # 文件上传
            file_name = public.GetRandomString(36)
            if int(args.up_content):
                # public.print_log("判断是否是上传邮件--{}--{}".format(args.up_content, type(args.up_content)))
                if not hasattr(args, 'file_content') or args.get('file_content', '') == '':
                    return public.returnMsg(False, '请上传邮件内容')
                content_path = "{}/content/{}".format(self.in_bulk_path, args.get('file_content', ''))
            # 内容编辑
            else:
                if not hasattr(args, 'content'):
                    return public.returnMsg(False, '请输入邮件内容')
                content_path = "{}/content/{}".format(self.in_bulk_path, file_name)
                if not os.path.exists("{}/content".format(self.in_bulk_path)):
                    os.mkdir("{}/content".format(self.in_bulk_path))
                public.WriteFile(content_path, json.dumps(args.content))

            # 收件人上传状态
            if not hasattr(args, 'file_recipient') or args.get('file_recipient', '') == '':
                return public.returnMsg(False, 'Parameter error')
            # 收件人路径(上传后处理的文件)
            recipient_path = "{}/recipient/verify_{}".format(self.in_bulk_path, args.get('file_recipient', ''))
            if not os.path.exists(recipient_path):
                return public.returnMsg(False, '请上传收件人')

            addresser = args.get('addresser/s', '')
            subject = args.get('subject/s', '')
            task_name = args.get('task_name/s', '')
            task_process = args.get('task_process', 0)  # 是否立即执行
            is_temp = args.get('is_temp', 0)  # 是否保存为模版

            # 发件人检测
            # addresser = args.addresser
            data = self.M('mailbox').where('username=?', addresser).find()
            if not data:
                return public.returnMsg(False, '邮件地址不存在')

            # 更新配置让黑名单生效
            shell_str = 'systemctl reload postfix'
            public.ExecShell(shell_str)

            # 添加前清除之前任务标记
            start_mark = '/www/server/panel/plugin/mail_sys/start_Task.pl'
            start_send = '/www/server/panel/plugin/mail_sys/start_Send.pl'
            end_mark = '/www/server/panel/plugin/mail_sys/end_Task.pl'
            if os.path.exists(start_mark):
                os.remove(start_mark)
            if os.path.exists(start_send):
                os.remove(start_send)
            if os.path.exists(end_mark):
                os.remove(end_mark)

            # 读取收件人总数
            recipient_count_path = "/www/server/panel/plugin/mail_sys/recipient_count"
            # 这里要进行错误处理
            recipient_count = int(public.ReadFile(recipient_count_path))

            # 添加邮件表
            timestamp = int(time.time())
            temp_id = 0
            task_id = 0

            try:
                temp_id = self.M('temp_email').add(
                    'name,addresser,recipient,subtype,subject,content,created,modified,is_temp',
                    (task_name, addresser, recipient_path, subtype, subject, content_path, timestamp, timestamp,
                     is_temp))

                # 添加任务表
                task_id = self.M('email_task').add(
                    'task_name,addresser,recipient_count,task_process,pause,temp_id,is_record,unsubscribe,threads,created,modified',
                    (task_name, addresser, recipient_count, task_process, 0, temp_id, is_record,unsubscribe,threads, timestamp, timestamp))

                # 记录发送失败日志
                error_log = "/www/server/panel/data/mail/in_bulk/errlog/{}_{}.log".format(task_name, task_id)
                if not os.path.exists(error_log):
                    public.WriteFile(error_log, '')

                # 添加执行的定时任务
                self._task_mail_send1()
                self._task_mail_send2()
                os.remove(recipient_count_path)

                return public.returnMsg(True, '任务添加成功')
            except Exception as e:
                public.print_log(public.get_error_info())
                # 删除已创建的任务
                self.M('temp_email').where('id=?', temp_id).delete()
                self.M('email_task').where('id=?', task_id).delete()
                # self.M('task_count').where('id=?', count_id).delete()
                return public.returnMsg(False, '任务添加失败: [{0}]'.format(str(e)))
        except Exception as e:
            public.print_log(public.get_error_info())

    # 暂停批量发送任务
    def pause_task(self, args):
        '''
        暂停发送任务   判断状态为执行中的可以暂停   task_process 1
        :param args: task_id 任务id;   pause 1暂停 0 重启
        :return:
        '''

        if not hasattr(args, 'task_id') or args.get('task_id/d', 0) == 0:
            return public.returnMsg(False, '参数错误')
        if not hasattr(args, 'pause'):
            return public.returnMsg(False, '参数错误')
        task_info = self.M('email_task').where('id=?', args.task_id).find()
        pause = int(args.pause)
        if pause == 1 and task_info['task_process'] != 1:
            return public.returnMsg(False, '只能暂停执行中的任务')

        task_process = 0 if pause else 1

        self.M('email_task').where('id=?', args.task_id).update({'pause': pause, "task_process": task_process})
        info = {
            "1": "暂停",
            # "0": "Restart"
            "0": "发送"
        }
        return public.returnMsg(True, '{}成功'.format(info[args.pause]))

    # 任务列表
    def get_task_list(self, args):
        '''
        任务列表
        :param args:
        :return:
        '''

        p = int(args.p) if 'p' in args else 1
        rows = int(args.size) if 'size' in args else 10
        callback = args.callback if 'callback' in args else ''
        count = self.M('email_task').count()
        page_data = public.get_page(count, p=p, rows=rows, callback=callback)

        try:
            task_list = self.M('email_task').order('created desc').limit(
                page_data['shift'] + ',' + page_data['row']).select()
            email_list = self.M('temp_email').order('created desc').field(
                'id,addresser,recipient,subtype,subject,content,is_temp').select()
            # public.print_log("email_list---{}".format(email_list))
            if not task_list:
                return public.returnMsg(True, {'data': [], 'page': page_data['page']})
            email_dict = {item['id']: item for item in email_list}
            for task in task_list:
                temp_id = task['temp_id']
                task_id = task['id']
                count = self.M('task_count').where('task_id=?', task_id).count()
                task['count'] = {"error_count": count}
                # 更新 email_info
                if temp_id in email_dict:
                    task['email_info'] = email_dict[temp_id]

                # 更新 count
                # if task_id in count_dict:
                #     task['count'] = count_dict[task_id]

                # 记录发送失败日志
                task['error_log'] = "/www/server/panel/data/mail/in_bulk/errlog/{}_{}.log".format(task['task_name'],
                                                                                                  task['id'])
                if not os.path.exists(task['error_log']):
                    public.WriteFile(task['error_log'], '')
            return public.returnMsg(True, {'data': task_list, 'page': page_data['page']})

        except Exception as e:
            public.print_log(public.get_error_info())

    # 删除任务

    def delete_task(self, args):
        '''
        删除任务
        :param args: task_id 任务id
        :return:
        '''
        if not hasattr(args, 'task_id') or args.get('task_id/d', 0) == 0:
            return public.returnMsg(False, '参数错误')
        task_info = self.M('email_task').where('id=?', args.task_id).find()
        # public.print_log("task_info--{}".format(task_info))
        # 删除错误日志
        error_log = "/www/server/panel/data/mail/in_bulk/errlog/{}_{}.log".format(task_info['task_name'],
                                                                                  task_info['id'])
        if os.path.exists(error_log):
            os.remove(error_log)
        try:
        # return error_log
            self.M('temp_email').where('id=?', task_info['temp_id']).delete()
            self.M('email_task').where('id=?', task_info['id']).delete()
            self.M('task_count').where('task_id=?', task_info['id']).delete()
            # public.print_log("aa--{},,,bb--{},,,cc--{}".format(aa, bb, cc))
        except:
            public.print_log(public.get_error_info())
        # 删除标记
        start_mark = '/www/server/panel/plugin/mail_sys/start_Task.pl'
        start_send = '/www/server/panel/plugin/mail_sys/start_Send.pl'
        end_mark = '/www/server/panel/plugin/mail_sys/end_Task.pl'
        if os.path.exists(start_mark):
            os.remove(start_mark)
        if os.path.exists(start_send):
            os.remove(start_send)
        if os.path.exists(end_mark):
            os.remove(end_mark)
        return public.returnMsg(True, '删除成功')

    # 获取错误数据分析
    def get_log_rank(self, args):
        '''
        获取错误排行
        :param args:
                task_id 任务id
                type     类型 domain 域名排行    status 错误类型排行
        :return:
        '''

        if not hasattr(args, 'type'):
            return public.returnMsg(False, '参数错误')

        types = args.type
        if types == "domain":
            field = "domain"
        else:
            field = "status"

        try:
            # offset = (p - 1) * rows

            # # SQL查询，使用占位符来安全地插入动态值
            # query = '''
            # SELECT {group_by_field}, COUNT(*) as count
            # FROM task_count
            # WHERE task_id = ?
            # GROUP BY {group_by_field}
            # ORDER BY count DESC
            # LIMIT ? OFFSET ?;
            # '''.format(group_by_field=field)
            #
            # params = (args.task_id, rows, offset)

            query = '''
            SELECT {group_by_field}, COUNT(*) as count
            FROM task_count
            WHERE task_id = ?
            GROUP BY {group_by_field}
            ORDER BY count DESC
            LIMIT 10;
            '''.format(group_by_field=field)

            params = (args.task_id,)
            # 执行查询
            results = self.M('task_count').query(query, params)
            # params = (args.task_id,)
            # results = self.M('task_count').query(query, params)
            rank_list = []

            for value, count in results:
                # rank_list.append({
                #     field:count
                # })
                rank_list.append({
                    field: value,
                    "count": count,
                })
        except:
            rank_list = []

        return public.returnMsg(True, rank_list)

    def get_log_list(self, args):
        '''
        获取错误详情
        :param args: task_id 任务id
        :return:
        '''
        if not hasattr(args, 'task_id') or args.get('task_id/d', 0) == 0:
            return public.returnMsg(False, '参数错误')

        p = int(args.p) if 'p' in args else 1
        rows = int(args.size) if 'size' in args else 10
        # callback = args.callback if 'callback' in args else ''

        if not hasattr(args, 'type'):
            return public.returnMsg(False, '参数错误')
        if not hasattr(args, 'value'):
            return public.returnMsg(False, '参数错误')

        types = args.type
        value = args.value
        if types == "domain":
            fields = "domain=?"
        else:
            fields = "status=?"

        # 查询条件
        wheres = 'task_id=? and ' + fields
        count = self.M('task_count').where(wheres, (args.task_id, value)).count()

        page_data = public.get_page(count, p=p, rows=rows, callback='')

        # 替换掉 href标签里的多余信息 只保留页码
        pattern =r"href='(/v2)?/plugin.*?\?p=(\d+)'"
        # 使用re.sub进行替换
        page_data['page'] = re.sub(pattern, r"href='\1'", page_data['page'])
        # public.print_log("page_data===>{}".format(page_data))
        try:

            query = self.M('task_count').where(wheres, (args.task_id, value))
            error_list = query.limit(page_data['shift'] + ',' + page_data['row']).select()
        except:
            error_list = []
        return public.returnMsg(True, {'data': error_list, 'page': page_data['page']})


    def _get_ptr_record(self):

        public_ip = self._get_pubilc_ip()
        if not public_ip:
            return False
        try:
            # 执行反向DNS查询
            result = socket.gethostbyaddr(public_ip)
            if result:
                if result[0]:
                    return True
            return False
        except socket.herror:
            return False

    def _task_mail_send1(self, ):

        # 查看是否有任务 没有结束 是否有执行中的任务 有 看执行状态
        # 查看任务是否已经开始执行  开始.pl -- 检查有没有结束 结束标记.pl
        # 没有开始标志 记录开始 开始.pl 去执行   执行  判断数量  分批次 延时执行
        #
        import crontab
        p = crontab.crontab()
        try:
            c_id = public.M('crontab').where('name=?', u'[勿删] 群发邮件任务').getField('id')
            if not c_id:
                data = {}
                data['name'] = u'[勿删] 群发邮件任务'
                data['type'] = 'minute-n'
                data['where1'] = '1'
                data['sBody'] = 'btpython /www/server/panel/plugin/mail_sys/script/send_bulk_script.py'
                data['backupTo'] = ''
                data['sType'] = 'toShell'
                data['hour'] = ''
                data['minute'] = ''
                data['week'] = ''
                data['sName'] = ''
                data['urladdress'] = ''
                data['save'] = ''
                p.AddCrontab(data)
                return public.returnMsg(True, '设置成功!')
        except Exception as e:
            public.print_log(public.get_error_info())

    # 检查有没有执行完毕  执行完毕 记录时间 修改状态 分析日志 更改统计 添加结束标记 删掉开始标记
    def _task_mail_send2(self, ):

        #
        import crontab
        p = crontab.crontab()
        try:
            c_id = public.M('crontab').where('name=?', u'[勿删] 检查发送结果').getField('id')
            if not c_id:
                data = {}
                data['name'] = u'[勿删] 检查发送结果'
                data['type'] = 'minute-n'
                data['where1'] = '1'
                data['sBody'] = 'btpython /www/server/panel/plugin/mail_sys/script/mail_error_logs.py'
                data['backupTo'] = ''
                data['sType'] = 'toShell'
                data['hour'] = ''
                data['minute'] = ''
                data['week'] = ''
                data['sName'] = ''
                data['urladdress'] = ''
                data['save'] = ''
                p.AddCrontab(data)
                return public.returnMsg(True, '设置成功!')
        except Exception as e:
            public.print_log(public.get_error_info())

    # 无订阅发送
    def _send_email_all(self, recipient_analysis, addresser, password, full_name, subject, content_detail, subtype,
                        is_record):
        # 登录
        send_mail_client = SendMail(addresser, password, 'localhost')
        # 邮件内容
        send_mail_client.setMailInfo(full_name, subject, content_detail, subtype, [])
        _, domain = addresser.split('@')
        # 收件人
        # for count, details in recipient_analysis.items():
        # for domain, details in recipient_analysis.items():
        #     if details['count'] == 0:
        #         continue
        #     mail_to = details['info']
        #     for user in mail_to:
        #         user_ = [user]
        #         # public.run_thread(send_mail_client.sendMail, (user_, domain, is_record))
        #         send_mail_client.sendMail(user_, domain, is_record)
        #         public.print_log("发送邮件--- {}".format(user))

        # 另一种 recipient_analysis 类型改  只有一个域名 不循环
        # recipient_analysis =  {"count": 0, "info": []}
        if recipient_analysis['count'] == 0:
            # public.print_log("无邮件退出")
            return
        mail_to = recipient_analysis['info']
        for user in mail_to:
            if len(user) == 0:
                continue
            user_ = [user]
            send_mail_client.sendMail(user_, domain, is_record)
            # public.print_log("发送邮件--- {}".format(user))

    #  正文需要增加退订按钮 发送方式
    def _send_email_all_unsubscribe(self, recipient_analysis, addresser, password, full_name, subject, content_detail,
                                    subtype, is_record):

        # 获取公网ip
        ip = public.readFile("/www/server/panel/data/iplist.txt")
        port = public.readFile('/www/server/panel/data/port.pl')
        ssl_staus = public.readFile('/www/server/panel/data/ssl.pl')
        if ssl_staus:
            ssl = 'https'
        else:
            ssl = 'http'
        # 登录
        send_mail_client = SendMail(addresser, password, 'localhost')
        # 邮件内容(原本位置)
        # send_mail_client.setMailInfo(full_name, subject, None, subtype, [])
        # 此处传递邮件发件人 主题
        send_mail_client.setMailInfo_one(full_name)
        # public.print_log("邮件主题--- {}".format(subject))
        _, domain = addresser.split('@')

        if recipient_analysis['count'] == 0:
            return
        mail_to = recipient_analysis['info']

        try:
            for user in mail_to:
                if len(user) == 0:
                    continue
                user_ = [user]
                # 更改发件内容  重新发送
                # 生成邮箱jwt
                mail_jwt = self.generate_jwt(user)

                # td = """<br><a href="{}://{}:{}/v2/plugin?action=a&name=mail_sys&s=Unsubscribe&jwt={}">Unsubscribe</a><br>""".format(
                #     ssl, ip, port, mail_jwt)
                td = """<div style="text-align: center;"><a href="{}://{}:{}/plugin?action=a&name=mail_sys&s=Unsubscribe&jwt={}">Unsubscribe</a></div>""".format(
                    ssl, ip, port, mail_jwt)
                # 找到 </html> 的位置
                position = content_detail.rfind('</html>')

                # 插入内容  加个换行
                if position != -1:
                    new_content = content_detail[:position] + td + content_detail[position:]
                else:
                    new_content = content_detail
                # public.print_log("邮件内容---{}".format(new_content))
                # 此处传入邮件正文
                send_mail_client.setMailInfo_two(subject, new_content, subtype, [])
                send_mail_client.sendMail(user_, domain, is_record)
                # public.print_log("发送邮件--- {}".format(user))
                # 重置msg对象
                send_mail_client.close()
        except:
            public.print_log(public.get_error_info())


    # 获取某个域名已经发送的数量
    def _get_count_limit(self, domain):
        key = domain
        # 获取已有的  每日凌晨1点清空
        count_sent = '/www/server/panel/plugin/mail_sys/count_sent_domain.json'
        if not os.path.exists(count_sent):
            data = {}
        else:
            try:
                data = public.readFile(count_sent)
                data = json.loads(data)
            except:
                data = {}

        return data.get(key, 0) or 0

    # 分析指定时间段内的日志 取出投递失败的记录
    def _mail_error_log(self, start, end, error_log, task_id):
        # public.print_log("取日志中----")
        try:

            path = '/var/log/maillog'
            if "ubuntu" in public.get_linux_distribution().lower():
                path = '/var/log/mail.log'

            log_data = public.readFile(path)

            # 正则表达式模式匹配投递结果信息
            status_pattern = r"\bstatus=([a-zA-Z0-9]+)\b"

            output_file1 = "/www/server/panel/data/mail/in_bulk/errlog"
            # output_file = "/www/server/panel/data/mail/in_bulk/errlog/task_err.log"
            if not os.path.isdir(output_file1):
                os.makedirs(output_file1)

            # 先清空
            with open(error_log, 'w') as f:
                pass

            seen_recipients = set()

            with open(error_log, 'a') as f:
                # 循环处理日志数据
                for line in log_data.splitlines():
                    err_one = {
                        "task_id": task_id,
                        "recipient": "",
                        "delay": "",
                        "delays": "",
                        "dsn": "",
                        "relay": "",
                        "domain": "",
                        "status": "",
                        "err_info": "",
                    }

                    try:

                        try:
                            # 尝试解析ISO 8601格式的时间戳
                            log_time = parse(line[:31])  # 取前31个字符 2024-07-12T08:32:04.211578+00:00
                            # 根据系统时区偏移时间

                        except ValueError:
                            # 如果ISO 8601格式解析失败，尝试解析另一种格式
                            timestamp_str = line[:15]  # 取前15个字符 Jul 12 16:37:12
                            try:
                                current_year = datetime.now().year
                                # 拼接年份
                                timestamp_str = f"{timestamp_str} {current_year}"
                                log_time = datetime.strptime(timestamp_str, '%b %d %H:%M:%S %Y')
                            except ValueError:
                                # public.print_log("报错 提取当前时间  当前:{} ".format(log_time))

                                # 记录为当前时间
                                log_time = datetime.now()

                        # log_time = log_time.timestamp()
                        log_time = int(log_time.timestamp())
                        # public.print_log("比较:  结束:{}  当前:{}  开始:{}".format(end, log_time, start))

                        if end >= log_time >= start:
                            match = re.search(status_pattern, line)
                            if match and (match.group(1) != "sent"):
                                # public.print_log("进入记录判断")
                                # 收件人邮箱
                                match1 = re.search(r'to=<([^>]+)>', line)
                                if match1:
                                    recipient = match1.group(1)
                                # 递送状态
                                match2 = re.search(r'status=([^ ]+)', line)
                                if match2:
                                    status = match2.group(1)
                                # 失败详情  (括号里的是失败详情)
                                match3 = re.search(r'\((.*?)\)', line)
                                if match3:
                                    err_info = match3.group(1)
                                # 总延时
                                match4 = re.search(r'delay=(\d+(\.\d+)?)', line)
                                if match4:
                                    delay = match4.group(1)
                                # 各阶段延时
                                match5 = re.search(r'delays=([\d./*]+)', line)
                                if match5:
                                    delays = match5.group(1)
                                # dsn
                                match6 = re.search(r'dsn=([\d.]+)', line)
                                if match6:
                                    dsn = match6.group(1)
                                # 中继服务器
                                match7 = re.search(r'relay=(.*?)(?=,| )', line)
                                if match7:
                                    relay = match7.group(1)

                                name, domain = recipient.split('@')
                                if name == 'postmaster':
                                    continue

                                else:
                                    # 记录详情 # 记录当前失败邮箱  失败原因  根据邮箱去重
                                    # err_one = {}
                                    err_one['recipient'] = recipient
                                    err_one['domain'] = domain
                                    err_one['status'] = status
                                    err_one['delay'] = delay
                                    err_one['delays'] = delays
                                    err_one['dsn'] = dsn
                                    err_one['relay'] = relay
                                    err_one['err_info'] = err_info
                                    if recipient not in seen_recipients:
                                        seen_recipients.add(recipient)
                                        f.write(line + '\n')
                                        self.M('task_count').insert(err_one)

                    except ValueError:
                        public.print_log(public.get_error_info())
                        pass
            return True
        except Exception as e:
            public.print_log(public.get_error_info())
            return False

    def _check_ptr_domain(self, domain):
        '''
        检测IP地址是否有PTR记录
        :param ip_address: IP地址字符串
        :return: bool
        '''

        try:
            ip_addresses = self._get_all_ip()
            ip_addresses = [ip for ip in ip_addresses if ip != '127.0.0.1']

            found_ptr_record = False
            result = None
            for ip_address in ip_addresses:
                if ':' in ip_address:  # IPv6
                    reverse_domain = self._ipv6_to_ptr(ip_address)
                else:  # IPv4
                    reverse_domain = '.'.join(reversed(ip_address.split('.'))) + '.in-addr.arpa'

                resolver = dns.resolver.Resolver()
                resolver.timeout = 5
                resolver.lifetime = 10

                try:
                    result = resolver.query(reverse_domain, 'PTR')
                    found_ptr_record = True
                    # public.print_log('找到, 退出')
                    break
                except dns.resolver.NoAnswer:
                    continue
            # 有记录
            if found_ptr_record:
                values = [str(rdata.target).rstrip('.') for rdata in result]
                # public.print_log('有记录  {}'.format(values))
                for i in values:
                    if i.endswith(domain):
                        return True
                    else:
                        continue
                return False
            return False

        except Exception as e:
            public.print_log(public.get_error_info())
            return False
    def check_ptr_domain(self, domain):
        '''
        查询域名和ip 用于安装webmail
        :param args:
        :return:
        '''
        key = '{0}:{1}'.format(domain, 'PTR')
        session = public.readFile('/www/server/panel/plugin/mail_sys/session.json')
        if session:
            session = json.loads(session)
        else:
            session = {}
        isptr = session[key]['status']
        return isptr
    def get_SECRET_KEY(self):
        path = '/www/server/panel/data/mail/jwt-secret.txt'
        if not os.path.exists(path):
            secretKey = public.GetRandomString(64)
            public.writeFile(path, secretKey)
        secretKey = public.readFile(path)
        return secretKey

    def generate_jwt(self, email):
        SECRET_KEY = self.get_SECRET_KEY()
        payload = {
            'email': email,
            'exp': datetime.utcnow() + timedelta(days=7)  # 7天过期
        }

        token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
        return token