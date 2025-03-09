import os
import sys
import glob
from datetime import datetime
if "/www/server/panel/class" not in sys.path:
    sys.path.insert(0, "/www/server/panel/class")

os.chdir("/www/server/panel")

from mod.project.ssh.base import SSHbase

class SecureManage(SSHbase):
    def __init__(self):
        super(SecureManage, self).__init__()

    def get_secure_logs(self, file_positions):
        """
        读取 /var/log/secure 日志文件的内容。

        :param file_path: secure 日志文件的路径
        :return: 日志内容的列表
        """
        new_logins = []
        current_positions = {}
        # 获取所有secure日志文件
        log_files = glob.glob('/var/log/secure*')

        for log_file in log_files:
            try:
                file_size = os.path.getsize(log_file)
                last_position = file_positions.get(log_file, 0)

                # 如果文件大小小于上次位置，说明文件被轮转过，从头开始读
                if file_size < last_position:
                    last_position = 0

                # 只有当文件有新内容时才处理
                if file_size > last_position:
                    with open(log_file, 'r') as f:
                        # 移动到上次处理的位置
                        f.seek(last_position)

                        # 读取新增的内容
                        for line in f:
                            if ("Accepted password" in line or
                                    "Failed password" in line or
                                    "Accepted publickey" in line):  # 添加对密钥登录的支持

                                parts = line.split()
                                year = datetime.now().year if "secure-" not in log_file else log_file.split("-")[-1][:4]
                                entry = self.parse_login_entry(parts, year)

                                if entry:
                                    entry["log_file"] = log_file
                                    new_logins.append(entry)

                        # 记录新的文件位置
                        current_positions[log_file] = f.tell()
                else:
                    # 如果文件没有变化，保持原来的位置
                    current_positions[log_file] = last_position

            except Exception as e:
                continue

        return new_logins, current_positions