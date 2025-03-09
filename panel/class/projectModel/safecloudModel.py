# coding: utf-8
# -------------------------------------------------------------------
# 宝塔Linux面板
# -------------------------------------------------------------------
# Copyright (c) 2014-2099 宝塔软件(http://bt.cn) All rights reserved.
# -------------------------------------------------------------------
# Author: wpl <wpl@bt.cn>
# -------------------------------------------------------------------

# 堡塔面板云安全检测-检测项：
# 1. 恶意文件检测[支持]
# 2. 首页风险[支持]
# 3. 网站漏洞扫描[支持]
# 4. 恶意进程检测[开发中……]
# 5. 蜜罐检测[开发中……]
# 6. 攻击链分析[开发中……]
# 
# ------------------------------
import os
import re
import json
import sys
import time
import threading
import queue
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any
import hashlib
import requests
import psutil
import fcntl  # 文件锁
from typing import Dict, List


os.chdir("/www/server/panel")
sys.path.append("class/")
import public
import config
from projectModel.base import projectBase


class WebshellDetector:
    """木马检测引擎基类
    @time: 2025-02-19
    """

    def detect(self, file_path: str) -> bool:
        raise NotImplementedError


class PatternDetector(WebshellDetector):
    """基于特征码的检测引擎
    @time: 2025-02-19
    """

    def __init__(self):
        self.rules = {
            'eval_pattern': r'(?:eval|assert)\s*\([^)]*(?:\$_(?:POST|GET|REQUEST|COOKIE)|base64_decode|gzinflate|str_rot13)',
            'system_pattern': r'(?:system|exec|shell_exec)\s*\([^)]*(?:\$|base64_decode)',
            'file_write_pattern': r'(?:file_put_contents|fwrite)\s*\([^,]+,\s*\$_(?:POST|GET)',
            'dangerous_functions': r'(?:passthru|popen|proc_open|create_function)\s*\(',
            'suspicious_encoding': r'(?:base64_decode\s*\(\s*strrev|str_rot13\s*\(\s*base64_decode)\s*\('
        }
        self.compiled_patterns = {name: re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                                  for name, pattern in self.rules.items()}

    def detect(self, file_path: str) -> tuple:
        """基于特征码的检测引擎
        @time: 2025-02-19
        @param file_path: 文件路径
        @return: 是否可疑, 规则名称
        """
        try:
            # 首先尝试 UTF-8
            encodings = ['utf-8', 'gbk', 'gb2312', 'iso-8859-1', 'latin1']
            content = None

            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    # logging.error("Error reading file {}: {}".format(file_path, str(e)))
                    return False, ''

            if content is None:
                # 如果所有编码都失败，使用二进制模式读取
                with open(file_path, 'rb') as f:
                    content = f.read().decode('utf-8', errors='ignore')

            # 添加基本过滤，跳过明显的二进制文件
            if b'\x00' in content.encode('utf-8'):
                return False, ''

            for name, pattern in self.compiled_patterns.items():
                if pattern.search(content):
                    return True, name
            return False, ''
        except Exception as e:
            # logging.error("Error scanning file {}: {}".format(file_path, str(e)))
            return False, ''


class BehaviorDetector(WebshellDetector):
    """基于行为分析的检测引擎
    @time: 2025-02-19
    @param file_path: 文件路径
    @return: 是否可疑, 规则名称
    """

    def detect(self, file_path: str) -> tuple:
        try:
            if os.access(file_path, os.X_OK):
                return True, 'executable_permission'

            if os.path.getsize(file_path) < 1024 and file_path.endswith(('.php', '.jsp')):
                return True, 'suspicious_size'

            return False, ''
        except Exception as e:
            # logging.error("Error analyzing file behavior {}: {}".format(file_path, str(e)))
            return False, ''


class YaraDetector(WebshellDetector):
    """基于 Yara 规则的检测引擎
    @time: 2025-02-19
    @param file_path: 文件路径
    @return: 是否可疑, 规则名称
    """

    RULE_CATEGORIES = {
        'webshells': '网站木马检测规则',
        'crypto': '加密挖矿检测规则'
    }

    def __init__(self):
        self.rules = {}  # 每个类别对应一个规则集
        self.base_path = '/www/server/panel/data/safeCloud/rules'
        self.rules_loaded = False
        self.rules_stats = {category: {'total': 0, 'loaded': 0} for category in self.RULE_CATEGORIES}
        self._load_all_rules()

    def _install_yara(self):
        """进程异步安装yara-python模块
        @return: bool
        """
        try:
            # 定义安装锁文件
            lock_file = '/tmp/install_yara.lock'
            
            # 检查是否已经在安装
            if os.path.exists(lock_file):
                return False
                
            # 创建锁文件
            public.writeFile(lock_file, str(time.time()))
            
            # 定义安装脚本
            install_script = '''#!/bin/bash
btpip install yara-python
rm -f /tmp/install_yara.lock
'''
            script_file = '/tmp/install_yara.sh'
            public.writeFile(script_file, install_script)
            public.ExecShell('chmod +x {}'.format(script_file))
            
            # 使用进程执行安装
            public.ExecShell('nohup {} >> /tmp/install_yara.log 2>&1 &'.format(script_file))
            return True
            
        except Exception as e:
            public.WriteLog('safecloud', 'yara-python安装失败: {}'.format(str(e)))
            if os.path.exists(lock_file):
                os.remove(lock_file)
            return False

    def check_yara(self):
        """检查并安装yara-python模块
        @return: bool
        """
        try:
            import yara
            return True
        except ImportError:
            self._install_yara()
            return False

    def _load_all_rules(self) -> None:
        """加载所有类别的规则
        @time: 2025-02-19
        @return: 是否加载成功
        """
        # 检查yara-python模块
        if not self.check_yara():
            return public.returnMsg(False, '正在安装所需的模块，请稍后重试')
        
        try:
            import yara
        except ImportError:
            return public.returnMsg(False, '依赖模块未安装，请稍后重试')

        try:
            # 确保基础规则目录存在
            # public.print_log("下载规则文件: {}".format(public.get_url()))
            if not os.path.exists(self.base_path):
                os.makedirs(self.base_path, mode=0o755)
                zip_file = "yara_rules.zip"
                downfile = os.path.join(self.base_path, zip_file)
                # public.downloadFile("{}/safeCloud/{}".format(public.get_url(), zip_file), downfile)
                
                o, e = public.ExecShell("unzip -o {} -d {}".format(downfile, self.base_path))
                # 解压报错
                if e != "":
                    # public.print_log("解压报错：{}".format(e))
                    return False
            
            # 加载每个类别的规则
            for category in self.RULE_CATEGORIES:
                category_path = os.path.join(self.base_path, category)

                # 确保类别目录存在
                if not os.path.exists(category_path):
                    os.makedirs(category_path, mode=0o755)
                    # public.print_log("Created rules directory for {}: {}".format(category, category_path))
                    continue

                # 获取该类别下的所有规则文件
                rule_files = {}
                for root, _, files in os.walk(category_path):
                    for file in files:
                        if file.endswith(('.yar', '.yara')):
                            self.rules_stats[category]['total'] += 1
                            name = "{}_{}".format(category, os.path.splitext(file)[0])
                            path = os.path.join(root, file)
                            rule_files[name] = path

                if rule_files:
                    try:
                        # 编译该类别的规则
                        self.rules[category] = yara.compile(filepaths=rule_files)
                        self.rules_stats[category]['loaded'] = len(rule_files)
                        # public.print_log("Successfully loaded {} rules for {}".format(len(rule_files), category))
                    except yara.Error as e:
                        # public.print_log("Error compiling rules for {}: {}".format(category, str(e)))
                        continue

            # 如果至少有一个类别的规则加载成功
            self.rules_loaded = bool(self.rules)

            # 输出规则加载统计
            # self._log_rules_stats()

        except Exception as e:
            # public.print_log("Error loading rules: {}".format(str(e)))
            pass

    def _log_rules_stats(self) -> None:
        """记录规则加载统计信息
        @time: 2025-02-19
        @return: 是否记录成功
        """
        stats = ["Yara rules loading statistics:"]
        for category, info in self.rules_stats.items():
            stats.append("- {}: {} rules loaded".format(category, info['loaded'] / info['total']))
        # public.print_log("\n".join(stats))

    def detect(self, file_path: str) -> tuple:
        """
        使用所有类别的 Yara 规则检测文件
        @time: 2025-02-19
        @param file_path: 文件路径
        @return: (is_suspicious: bool, rule_name: str) 是否可疑, 规则名称
        """
        if not self.rules_loaded:
            # public.print_log("No Yara rules loaded, attempting to reload...")
            self._load_all_rules()
            if not self.rules_loaded:
                return False, ''

        try:
            # 基础文件检查
            if not os.path.exists(file_path) or not os.access(file_path, os.R_OK):
                # public.print_log("File not accessible: {}".format(file_path))
                return False, ''

            file_size = os.path.getsize(file_path)
            if file_size > 10 * 1024 * 1024:  # 10MB
                # public.print_log("File too large to scan: {} ({})".format(file_path, file_size))
                return False, ''

            # 对每个类别的规则进行检测
            for category, rules in self.rules.items():
                try:
                    matches = rules.match(file_path, timeout=60)
                    if matches:
                        rule_name = matches[0].rule
                        match_details = []

                        # 收集匹配详情
                        for match in matches[0].strings:
                            match_details.append("{}: {}".format(match[1], match[2].decode('utf-8', errors='ignore')))

                        # 记录详细的匹配信息
                        # public.print_log(
                        #     "Yara detection in category '{}':\n"
                        #     "- File: {}\n"
                        #     "- Rule: {}\n"
                        #     "- Matched strings: {}".format(category, file_path, rule_name, ', '.join(match_details))
                        # )

                        return True, "yara_{}_{}".format(category, rule_name)

                except yara.TimeoutError:
                    # public.print_log("Yara scan timeout for {} in {}".format(file_path, category))
                    pass
                except yara.Error as e:
                    # public.print_log("Yara scan error for {} in {}: {}".format(file_path, category, str(e)))
                    pass
                except Exception as e:
                    # public.print_log("Unexpected error scanning {} in {}: {}".format(file_path, category, str(e)))
                    pass
            return False, ''

        except Exception as e:
            # public.print_log("Global error in Yara scan for {}: {}".format(file_path, str(e)))
            return False, ''

    def get_rules_status(self) -> dict:
        """获取规则加载状态统计信息
        @time: 2025-02-19
        @return: <dict>规则加载状态统计信息
        """
        return {
            'total_categories': len(self.RULE_CATEGORIES),
            'loaded_categories': len(self.rules),
            'stats_by_category': self.rules_stats,
            'is_functional': self.rules_loaded
        }


class CloudDetector(WebshellDetector):
    """云端检测引擎
    @time: 2025-02-19
    @param file_path: 文件路径
    @return: <tuple> 是否可疑, 规则名称
    """

    def __init__(self):
        self.cache_file = '/www/server/panel/data/safeCloud/cloud_config.json'
        self.url_cache = self._load_cache() # 加载缓存配置
        self.last_check_time = self.url_cache.get('last_check', 0) # 上次检查时间
        self.check_url = self.url_cache.get('check_url', '') # 检测URL
        self.request_count = 0 # 请求次数
        self.last_request_time = 0 # 上次请求时间
        # 配置参数
        self.cache_ttl = 86400  # URL缓存时间(24小时)
        self.rate_limit = {
            'max_requests': 100,  # 每小时最大请求数
            'interval': 3600,  # 计数周期(秒)
            'min_interval': 1  # 两次请求的最小间隔(秒)
        }

    def _load_cache(self) -> dict:
        """加载缓存配置
        @time: 2025-02-19
        @return: <dict> 缓存配置
        """
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            # logging.error("Error loading cloud config cache: {}".format(str(e)))
            pass
        return {'last_check': 0, 'check_url': ''}

    def _save_cache(self) -> None:
        """保存缓存配置
        @time: 2025-02-19
        """
        try:
            cache_dir = os.path.dirname(self.cache_file)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            with open(self.cache_file, 'w') as f:
                json.dump({
                    'last_check': self.last_check_time,
                    'check_url': self.check_url
                }, f)
        except Exception as e:
            # logging.error("Error saving cloud config cache: {}".format(str(e)))
            pass

    def _update_check_url(self) -> bool:
        """更新检测URL
        @time: 2025-02-19
        @return: <bool> 是否更新成功
        """
        current_time = time.time()

        # 检查缓存是否有效
        if self.check_url and (current_time - self.last_check_time) < self.cache_ttl:
            return True

        try:
            ret = requests.get('http://www.bt.cn/checkWebShell.php').json()
            if ret['status'] and ret['url']:
                self.check_url = ret['url']
                self.last_check_time = current_time
                self._save_cache()
                return True
        except Exception as e:
            # logging.error("Error updating check URL: {}".format(str(e)))
            pass
        return False

    def _check_rate_limit(self) -> bool:
        """检查频率限制
        @time: 2025-02-19
        @return: <bool> 是否检查成功
        """
        current_time = time.time()

        # 检查最小请求间隔
        # if (current_time - self.last_request_time) < self.rate_limit['min_interval']:
        #     return False

        # 重置计数器
        if (current_time - self.last_request_time) > self.rate_limit['interval']:
            self.request_count = 0

        # 检查请求数限制
        if self.request_count >= self.rate_limit['max_requests']:
            return False

        self.request_count += 1
        self.last_request_time = current_time
        return True

    def detect(self, file_path: str) -> tuple:
        """检测文件是否为木马
        @time: 2025-02-19
        @param file_path: 文件路径
        @return: <tuple> 是否可疑, 规则名称
        """
        try:
            # 基础检查
            if not os.path.exists(file_path) or not os.path.isfile(file_path):
                return False, ''

            # 检查文件大小
            file_size = os.path.getsize(file_path)
            if file_size < 1024:  # 小于1KB，视为空文件
                return False, ''
            if file_size > 10 * 1024 * 1024:  # 10MB限制
                return False, ''

            # 频率限制检查
            if not self._check_rate_limit():
                logging.warning("Cloud detection rate limit exceeded for: {}".format(file_path))
                return False, ''

            # 确保有可用的检测URL
            if not self._update_check_url():
                return False, ''

            # 读取文件内容
            file_content = self.ReadFile(file_path)
            if not file_content:
                return False, ''

            # 计算文件MD5
            md5_hash = self.FileMd5(file_path)
            if not md5_hash:
                return False, ''

            # 发送检测请求
            try:
                upload_data = {
                    'inputfile': file_content,
                    'md5': md5_hash
                }
                response = requests.post(self.check_url, upload_data, timeout=20)
                # 添加响应内容检查
                if not response.content:
                    # logging.error("Empty response from cloud detection for file: {}".format(file_path))
                    return False, ''
                try:
                    result = response.json()
                except json.JSONDecodeError as je:
                    # logging.error("Invalid JSON response from cloud detection for {}: {}".format(file_path, response.content))
                    return False, ''

                # 查看是否需要告警
                if isinstance(result, dict) and result.get('msg') == 'ok':
                    try:
                        is_webshell = result.get('data', {}).get('data', {}).get('level') == 5
                        if is_webshell:
                            return True, 'cloud_detection'
                    except (KeyError, AttributeError) as e:
                        # logging.error("Unexpected response structure for {}: {}".format(file_path, result))
                        return False, ''

            except Exception as e:
                # logging.error("Cloud detection error for {}: {}".format(file_path, str(e)))
                pass

            return False, ''

        except Exception as e:
            # logging.error("Error in cloud detection: {}".format(str(e)))
            return False, ''

    def ReadFile(self, filepath: str, mode: str = 'r') -> str:
        """读取文件内容
        @time: 2025-02-19
        @param filepath: 文件路径
        @param mode: 文件模式
        @return: <str> 文件内容
        """
        if not os.path.exists(filepath):
            return ''
        try:
            with open(filepath, mode) as fp:
                return fp.read()
        except Exception:
            try:
                with open(filepath, mode, encoding="utf-8") as fp:
                    return fp.read()
            except Exception as e:
                # logging.error("Error reading file {}: {}".format(filepath, str(e)))
                return ''

    def FileMd5(self, filepath: str) -> str:
        """计算文件MD5
        @time: 2025-02-19
        @param filepath: 文件路径
        @return: <str> 文件MD5
        """
        try:
            if not os.path.exists(filepath) or not os.path.isfile(filepath):
                return ''
            md5_hash = hashlib.md5()
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(64 * 1024), b''):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            # logging.error("Error calculating MD5 for {}: {}".format(filepath, str(e)))
            return ''

class SafeCloudModel:
    # 恶意文件 云端上报配置[目前不给支持]
    def __init__(self):
        self.upload_config = {
            'url': 'http://w-check.bt.cn/upload_web.php',
            'max_file_size': 2 * 1024 * 1024,  # 最大文件大小限制(1MB)
            'max_daily_uploads': 50,  # 每日最大上报数量
            'min_upload_interval': 300,  # 最小上报间隔(秒)
            'cache_file': '/www/server/panel/data/safeCloud/upload_stats.json'
        }
        self.upload_stats = self._load_upload_stats()

    def _load_upload_stats(self) -> dict:
        """加载上报统计数据
        @return: dict 上报统计信息
        """
        try:
            if os.path.exists(self.upload_config['cache_file']):
                with open(self.upload_config['cache_file'], 'r') as f:
                    stats = json.load(f)
                    # 检查是否需要重置每日统计
                    if stats.get('date') != time.strftime('%Y-%m-%d'):
                        stats = self._reset_upload_stats()
                    return stats
        except Exception as e:
            # logging.error("加载上报统计数据失败: {}".format(str(e)))
            pass
        return self._reset_upload_stats()

    def _get_upload_filename(self, file_path: str) -> str:
        """生成上传文件名
        @param file_path: 文件路径
        @return: str 处理后的文件名 (format: filename_timestamp.ext)
        """
        try:
            # 获取原始文件名和扩展名
            filename, ext = os.path.splitext(os.path.basename(file_path))
            
            # 获取当前时间戳
            timestamp = str(int(time.time()))
                
            # 构造新文件名: 原文件名_时间戳.扩展名
            return "{}_{}.{}".format(filename, timestamp, ext)
        except Exception as e:
            # 出错时返回原文件名
            return os.path.basename(file_path)

    def _reset_upload_stats(self) -> dict:
        """重置上报统计数据
        @return: dict 初始化的统计信息
        """
        return {
            'date': time.strftime('%Y-%m-%d'),
            'count': 0,
            'last_upload_time': 0,
            'uploaded_files': []  # 记录已上报的文件MD5
        }

    def _save_upload_stats(self) -> None:
        """保存上报统计数据"""
        try:
            cache_dir = os.path.dirname(self.upload_config['cache_file'])
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            with open(self.upload_config['cache_file'], 'w') as f:
                json.dump(self.upload_stats, f)
        except Exception as e:
            # logging.error("保存上报统计数据失败: {}".format(str(e)))
            pass

    def _check_upload_limits(self, file_path: str) -> tuple:
        """检查上报限制
        @param file_path: 文件路径
        @return: (bool, str) 是否可以上报，原因
        """
        current_time = time.time()

        # 检查文件大小
        try:
            if os.path.getsize(file_path) > self.upload_config['max_file_size']:
                return False, "文件超过大小限制"
        except Exception:
            return False, "无法获取文件大小"

        # 检查是否已上报过该文件
        file_md5 = self.FileMd5(file_path)
        if file_md5 in self.upload_stats['uploaded_files']:
            return False, "文件已上报"

        # 检查日期是否需要重置
        if self.upload_stats['date'] != time.strftime('%Y-%m-%d'):
            self.upload_stats = self._reset_upload_stats()

        # 检查每日上报数量
        if self.upload_stats['count'] >= self.upload_config['max_daily_uploads']:
            return False, "超过每日上报限制"

        # 检查最小上报间隔
        if (current_time - self.upload_stats['last_upload_time']) < self.upload_config['min_upload_interval']:
            return False, "上报过于频繁"

        return True, ""

    def upload_malicious_file(self, file_path: str, rule_name: str) -> bool:
        """上报恶意文件
        @param file_path: 文件路径
        @param rule_name: 规则名称
        @return: bool 是否上报成功
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return False

            # 检查上报限制
            can_upload, reason = self._check_upload_limits(file_path)
            if not can_upload:
                # logging.warning("文件上报受限 {}: {}".format(file_path, reason))
                return False

            # 生成带时间戳的上传文件名
            upload_filename = self._get_upload_filename(file_path)

            # 准备上报数据
            upload_data = {
                'filename': upload_filename,
                'rule_name': rule_name,
                'upload_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }

            # 读取文件内容
            try:
                with open(file_path, 'rb') as f:
                    files = {
                        'file': (upload_data['filename'], f),
                        'data': ('data.json', json.dumps(upload_data))
                    }
                    
                    # 发送上报请求
                    response = requests.post(
                        self.upload_config['url'],
                        files=files,
                        timeout=30
                    )

                    if response.status_code == 200:
                        # 更新统计信息
                        self.upload_stats['count'] += 1
                        self.upload_stats['last_upload_time'] = time.time()
                        self.upload_stats['uploaded_files'].append(self.FileMd5(file_path))
                        self._save_upload_stats()
                        # logging.info("恶意文件上报成功: {}".format(file_path))
                        return True
                    else:
                        # logging.error("恶意文件上报失败 {}: HTTP {}".format(file_path, response.status_code))
                        return False

            except Exception as e:
                # logging.error("上报文件时发生错误 {}: {}".format(file_path, str(e)))
                return False

        except Exception as e:
            # logging.error("处理文件上报时发生错误: {}".format(str(e)))
            pass

class Config:
    """配置管理类
    @time: 2025-02-19
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> Dict:
        """加载配置文件
        @time: 2025-02-19
        @return: <dict> 配置文件
        """
        default_config = {
            'monitor_dirs': ['/', '/www/server/php'],
            'supported_exts': ['.php', '.jsp', '.asp', '.aspx'],
            'scan_interval': 3600, # 扫描间隔 6小时 = 21600秒
            'max_threads': 4,
            'log_level': 'INFO',
            'dynamic_detection': True,  # 动态查杀开关,默认开启
            # 过滤目录
            'exclude_dirs': [
                '/proc',
                '/sys',
                '/dev',
                '/tmp',
                '/run',
                '/media',
                '/mnt',
                '/boot',
                '/www/server/php',
                '/www/server/panel/logs',
                '/usr/src/',
                '/www/server/panel/pyenv/',
                '/.Recycle_bin/',
                '/www/server/panel/plugin/',
                '/var/lib/docker/'
            ],
            'max_file_size': 5 * 1024 * 1024,  # 5MB
            'scan_delay': 0.1,  # 每个文件扫描后的延迟(秒)
            'skipped_dirs': {},  # 存储跳过的目录信息，格式: {'dir_path': {'file_count': count, 'mtime': timestamp}}
            'max_files_per_dir': 10000,  # 每个目录的最大文件数限制
            'quarantine': False,  # 是否隔离文件，默认为False
            "alertable": {
                "status": True,  # 是否开启告警
                "safe_type": ["webshell"],  # 告警功能,webshell木马
                "sender": [],  # 告警方法
                "interval": 10800,  # 告警间隔 3小时告警一次
                "time_rule": {
                    "send_interval": 600  # 告警发送间隔 10分钟发送一次
                },
                "number_rule": {
                    "day_num": 20  # 告警发送数量 20个
                }
            }
        }

        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            else:
                # 如果配置文件不存在，创建一个新的
                with open(self.config_path, 'w') as f:
                    json.dump(default_config, f, indent=4)
                # logging.info("Created new config file at {}".format(self.config_path))
                pass
        except Exception as e:
            # logging.error("Error handling config file: {}".format(str(e)))
            pass

        return default_config

    def save_config(self) -> None:
        """保存配置文件
        @time: 2025-02-19
        @return: <None> 保存配置文件
        """
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            # logging.error("Error saving config: {}".format(str(e)))
            pass

    def update_skipped_dirs(self, dir_path: str, file_count: int, mtime: float) -> None:
        """更新跳过目录的信息
        @time: 2025-02-19
        @param dir_path: 目录路径
        @param file_count: 文件数量
        @param mtime: 修改时间
        @return: <None> 更新跳过目录的信息
        """
        try:
            self.config['skipped_dirs'][dir_path] = {
                'file_count': file_count,
                'mtime': mtime
            }
            self.save_config()
        except Exception as e:
            # logging.error("Error updating skipped dirs: {}".format(str(e)))
            pass

    def is_dir_skipped(self, dir_path: str, current_mtime: float) -> bool:
        """检查目录是否应该被跳过
        @time: 2025-02-19
        @param dir_path: 目录路径
        @param dir_path: 目录路径
        @param current_mtime: 当前修改时间
        @return: <bool> 是否跳过
        """
        if dir_path in self.config['skipped_dirs']:
            # 如果目录的修改时间没有变化，继续跳过
            if self.config['skipped_dirs'][dir_path]['mtime'] == current_mtime:
                return True
            # 如果修改时间变化了，移除跳过标记
            else:
                del self.config['skipped_dirs'][dir_path]
                self.save_config()
        return False


class main(projectBase):
    def __init__(self):
        self.__path = '/www/server/panel/data/safeCloud'
        # 确保配置目录存在
        if not os.path.exists(self.__path):
            os.makedirs(self.__path, mode=0o755)
        self.__config = Config(os.path.join(self.__path, 'config.json'))

        # 创建日志目录
        self.__log_dir = os.path.join(self.__path, 'log')
        self.__log_file = os.path.join(self.__log_dir, 'detection_{}.log'.format(
            time.strftime("%Y%m%d")
        ))

        # 初始化检测引擎:正则匹配\行为分析\yara规则匹配\clamv检测\机器分析
        self.__detectors = [
            PatternDetector(),  # 正则匹配
            # BehaviorDetector(),  # 行为分析
            YaraDetector(),  # 添加 Yara 检测引擎
            CloudDetector()  # 添加云查杀引擎
        ]

        # 创建必要的目录
        self.__risk_files = os.path.join(self.__path, 'risk_files')
        self.__last_scan = os.path.join(self.__path, 'last_scan.json')
        self.__dir_record = os.path.join(self.__path, 'dir_record.json')

        for path in [self.__path, self.__risk_files, self.__log_dir]:
            if not os.path.exists(path):
                os.makedirs(path)

    # 初始化告警配置 外部接口,给告警配置提供初始化配置
    def init_config(self, get=None):
        return {}

    def get_file_info(self, file_path: str) -> Dict:
        """获取文件信息
        @time: 2025-02-19
        @param file_path: 文件路径
        @return: <dict> 文件信息
        """
        return {
            'path': file_path,
            'mtime': os.path.getmtime(file_path),
            'size': os.path.getsize(file_path)
        }

    def FileMd5(self, filepath):
        """
        @time: 2025-02-19
        @name 生成文件的MD5
        @param filename 文件路径
        @return string(32): 文件的MD5值，失败时返回空字符串
        """
        try:
            if not filepath or not os.path.exists(filepath) or not os.path.isfile(filepath):
                return ''
            import hashlib
            md5_hash = hashlib.md5()
            # 分块读取文件（64KB），避免大文件占用过多内存
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(64 * 1024), b''):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            # public.print_log("Error calculating MD5 for {}: {}".format(filepath, str(e)))
            return ''

    def write_detection_log(self, file_path: str, rule_name: str, is_quarantined: bool = False) -> None:
        """写入检测日志
        @time: 2025-02-19
        @param file_path: 文件路径
        @param rule_name: 匹配规则
        @param is_quarantined: 是否已隔离
        """
        try:
            # 获取文件MD5
            md5_hash = self.FileMd5(file_path)

            # 根据规则确定风险等级 0-低危 1-中危 2-高危
            risk_level = 2

            # 构建日志条目
            log_entry = "{}|{}|{}|{}|{}|{}|{}|{}|{}\n".format(
                os.path.basename(file_path),  # 文件名
                file_path,  # 文件完整路径
                "WebShell",  # 威胁标签
                md5_hash,  # 文件MD5
                risk_level,  # 风险等级
                time.strftime("%Y-%m-%d %H:%M:%S"),  # 发现时间
                "true" if is_quarantined else "false",  # 是否隔离
                rule_name,  # 匹配规则
                "0"  # 处理状态(0:未处理, 1:已处理)
            )

            # 定义要写入的日志文件列表
            log_files = [
                # 总日志文件
                os.path.join(self.__log_dir, "detection_all.log"),
                # 当天日志文件
                os.path.join(self.__log_dir, "detection_{}.log".format(
                    time.strftime("%Y%m%d")
                ))
            ]

            # 写入所有日志文件
            for log_file in log_files:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(log_entry)
                except Exception as e:
                    # logging.error("Error writing to log file {}: {}".format(log_file, str(e)))
                    pass

        except Exception as e:
            # logging.error("Error in write_detection_log: {}".format(str(e)))
            pass

    def _get_risk_level(self, rule_name: str) -> int:
        """根据规则确定风险等级
        @time: 2025-02-19
        @param rule_name: 规则名称
        @return: 0-低危 1-中危 2-高危
        """
        high_risk_rules = ['eval_pattern', 'system_pattern']
        medium_risk_rules = ['file_write_pattern', 'dangerous_functions']

        if rule_name in high_risk_rules:
            return 2
        elif rule_name in medium_risk_rules:
            return 1
        return 0

    def scan_file(self, file_path: str) -> tuple:
        """检查单个文件
        @time: 2025-02-19
        @param file_path: 文件路径
        @return: <tuple> 是否可疑, 规则名称
        """
        try:
            # 获取检测引擎:正则匹配, 行为分析, yara规则匹配, clamv检测
            for detector in self.__detectors:
                is_suspicious, rule = detector.detect(file_path)
                if is_suspicious:
                    return True, rule
            return False, ''
        except Exception as e:
            return False, ''

    def handle_suspicious_file(self, file_path: str, rule_name: str) -> bool:
        """处理可疑文件
        @time: 2025-02-19
        @param file_path: 文件路径
        @param rule_name: 规则名称
        @return: 是否处理成功
        """
        try:
            filename = "{}_{}".format(
                os.path.basename(file_path),
                time.strftime("%Y%m%d_%H%M%S")
            )
            quarantine_path = os.path.join(self.__risk_files, filename)
            # 记录日志
            self.write_detection_log(file_path, rule_name, self.__config.config['quarantine'])

            # 移动文件到隔离区
            # os.rename(file_path, quarantine_path)
            self.Mv_Recycle_bin(file_path)
            # public.print_log("|============file_path:{}".format(file_path))

            return True
        except Exception as e:
            # print("Error handling suspicious file {}: {}".format(file_path, str(e)))
            return False

    def get_dir_info(self, dir_path: str) -> Dict:
        """获取目录信息
        @param dir_path: 目录路径
        @return: 目录信息字典
        """
        try:
            return {
                'mtime': os.path.getmtime(dir_path),
                'file_count': 0,  # 记录目录中的文件数量
                'skip': False,  # 是否跳过该目录
                'depth': len(dir_path.split(os.sep))  # 添加目录深度信息
            }
        except Exception as e:
            # logging.error("Error getting directory info for {}: {}".format(dir_path, str(e)))
            return None

    def cpu_guard(self, max_usage=7, max_sleep=10):
        """动态节流控制器
        @param max_usage: 最大CPU使用率阈值(%)
        @param max_sleep: 最大睡眠时间(秒)
        """
        try:
            current_cpu = psutil.cpu_percent(interval=0.1)
            if current_cpu > max_usage:
                # 计算建议的睡眠时间
                sleep_time = 0.5 * (current_cpu / max_usage)
                # 限制最大睡眠时间
                sleep_time = min(sleep_time, max_sleep)
                time.sleep(sleep_time)
        except Exception as e:
            # 如果获取CPU使用率失败，使用最小睡眠时间
            time.sleep(0.5)

    def get_new_files(self) -> List[str]:
        """获取新增或修改的文件列表
        @time: 2025-02-19
        @return: 新增或修改的文件列表
        """
        new_files = []
        current_dirs = {}
        total_files = 0  # 当次扫描的文件数
        MAX_DEPTH = 20  # 最大深度
        MAX_FILES_PER_DIR = 10000  # 单个目录最大文件数

        try:
            # 加载目录记录
            dir_record = self.load_dir_record()
            last_dirs = dir_record.get('directories', {})
            is_first_scan = not bool(last_dirs)

            # 使用栈进行深度优先搜索
            dir_stack = []
            processed_dirs = set()

            # 初始化目录栈
            for base_dir in self.__config.config['monitor_dirs']:
                if os.path.exists(base_dir):
                    dir_info = self.get_dir_info(base_dir)
                    if dir_info:
                        dir_stack.append((base_dir, dir_info['depth']))

            while dir_stack:
                current_dir, current_depth = dir_stack[-1]  # 查看栈顶元素但不移除

                # 如果当前目录已处理，弹出并继续
                if current_dir in processed_dirs:
                    dir_stack.pop()
                    continue

                # 检查目录深度,超过20层
                if current_depth > MAX_DEPTH:
                    # public.print_log("目录 {} 深度超过{}层，已跳过".format(current_dir, MAX_DEPTH))
                    self.__config.update_skipped_dirs(current_dir, 0, os.path.getmtime(current_dir))
                    processed_dirs.add(current_dir)  # 添加到已处理集合
                    dir_stack.pop()
                    continue

                # 跳过排除目录和符号链接
                if (current_dir in self.__config.config['exclude_dirs'] or
                        os.path.islink(current_dir)):
                    processed_dirs.add(current_dir)  # 添加到已处理集合
                    dir_stack.pop()
                    continue
                try:
                    # 获取当前目录信息
                    current_mtime = os.path.getmtime(current_dir)

                    # 检查目录是否应该被跳过
                    if self.__config.is_dir_skipped(current_dir, current_mtime):
                        # public.print_log("目录 {} 已被标记为跳过".format(current_dir))
                        processed_dirs.add(current_dir)  # 添加到已处理集合
                        dir_stack.pop()
                        continue

                    # 获取子目录
                    subdirs = []
                    try:
                        with os.scandir(current_dir) as entries:
                            for entry in entries:
                                if entry.is_dir(follow_symlinks=False):
                                    dir_path = entry.path
                                    if (dir_path not in self.__config.config['exclude_dirs'] and
                                            dir_path not in processed_dirs):
                                        # 检查子目录深度
                                        child_depth = current_depth + 1
                                        if child_depth <= MAX_DEPTH:  # 只添加不超过最大深度的目录
                                            subdirs.append((dir_path, child_depth))
                                        else:
                                            # 直接标记超深的子目录为已处理
                                            processed_dirs.add(dir_path)
                                            self.__config.update_skipped_dirs(dir_path, 0, os.path.getmtime(dir_path))
                                            # public.print_log("子目录 {} 深度超过{}层，已跳过".format(dir_path, MAX_DEPTH))
                    except Exception as e:
                        # logging.error("扫描目录 {} 时出错: {}".format(current_dir, str(e)))
                        processed_dirs.add(current_dir)  # 添加到已处理集合
                        dir_stack.pop()
                        continue

                    # 如果有未处理的子目录，将它们加入栈中
                    if subdirs:
                        dir_stack.extend(subdirs)
                        continue

                    # 到达最深处的目录，开始处理文件
                    dir_stack.pop()
                    processed_dirs.add(current_dir)

                    # 非首次扫描时检查目录时间是否变化
                    if not is_first_scan and current_dir in last_dirs:
                        last_mtime = last_dirs[current_dir].get('mtime', 0)
                        if current_mtime == last_mtime:
                            continue

                    # 处理当前目录中的文件
                    file_count = 0
                    current_time = time.time()

                    with os.scandir(current_dir) as entries:
                        for entry in entries:
                            if entry.is_file(follow_symlinks=False):
                                file_count += 1
                                total_files += 1

                                # 检查文件数量限制
                                if file_count > MAX_FILES_PER_DIR:
                                    # public.print_log(
                                    #     "目录 {} 文件数量超过{}个，已标记为跳过".format(current_dir, MAX_FILES_PER_DIR))
                                    self.__config.update_skipped_dirs(current_dir, file_count, current_mtime)
                                    break

                                # 每处理100个文件,进行动态休眠
                                if file_count % 100 == 0:
                                    self.cpu_guard()

                                file_path = entry.path
                                if os.path.splitext(file_path)[1].lower() in self.__config.config['supported_exts']:
                                    try:
                                        file_stat = entry.stat()
                                        if file_stat.st_size > self.__config.config['max_file_size']:
                                            continue

                                        file_mtime = file_stat.st_mtime
                                        # 检查是否为新文件（60秒内）
                                        if current_time - file_mtime <= 60:
                                            # public.print_log("发现新文件: {}".format(file_path))
                                            new_files.append(file_path)

                                    except Exception as e:
                                        # logging.error("处理文件 {} 时出错: {}".format(file_path, str(e)))
                                        continue

                    # 更新目录信息
                    current_dirs[current_dir] = {
                        'mtime': current_mtime,
                        'file_count': file_count,
                        'depth': current_depth
                    }

                except Exception as e:
                    # logging.error("处理目录 {} 时出错: {}".format(current_dir, str(e)))
                    processed_dirs.add(current_dir)  # 添加到已处理集合
                    dir_stack.pop()
                    continue

            # 1. 保存当前扫描状态
            self.save_current_scan({
                'scan_time': time.time(),
                'total_files': total_files,
                'is_first_scan': False
            })
            # 2. 保存目录记录
            self.save_dir_record({
                'directories': current_dirs,
                'last_update': time.time()
            })

        except Exception as e:
            # logging.error("Error in get_new_files: {}".format(str(e)))
            pass

        return new_files

    def scan_suspicious_files(self, file_list: List[str]) -> List[str]:
        """对文件列表进行木马查杀
        @time: 2025-02-19
        @param file_list: 文件列表
        @return: <list> 可疑文件列表
        """
        detected_webshells = []
        try:
            for file_path in file_list:
                try:
                    is_suspicious, rule = self.scan_file(file_path)
                    if is_suspicious:
                        # 如果文件是可疑的，判断是否需要隔离处理
                        if self.__config.config['quarantine']:
                            self.handle_suspicious_file(file_path, rule)
                        else:
                            self.write_detection_log(file_path, rule)
                        detected_webshells.append(file_path)
                except Exception as e:
                    # logging.error("Error scanning file {}: {}".format(file_path, str(e)))
                    continue
            if detected_webshells:
                self.send_webshell_batch_alert(detected_webshells)
        except Exception as e:
            # logging.error("Error in scan_suspicious_files: {}".format(str(e)))
            pass

        return detected_webshells
    
    # 主要检测入口
    def webshell_detection(self, get: Dict) -> Dict:
        """主要检测入口
        @time: 2025-02-19
        @param get: 请求参数
        @return: <dict> 检测结果
        """
        try:
            # public.print_log("|-开始木马检测扫描-|")
            # 检测是否开启动态查杀开关
            if not self.__config.config.get('dynamic_detection', True):
                return public.returnMsg(True, '动态查杀功能已关闭，跳过检测')
            # # 检查扫描间隔
            # last_scan_info = self.load_last_scan()
            # current_time = time.time()
            # if last_scan_info and current_time - last_scan_info.get('scan_time', 0) < self.__config.config[
            #     'scan_interval']:
            #     return public.returnMsg(True, '距离上次扫描时间不足{}小时'.format(
            #         self.__config.config['scan_interval'] / 3600
            #     ))

            # task任务频率控制：6小时执行一次
            safecloud_dir = '/www/server/panel/data/safeCloud'
            if not os.path.exists(safecloud_dir):
                os.makedirs(safecloud_dir)
                
            last_detection_file = '{}/last_detection_time.json'.format(safecloud_dir)
            current_time = int(time.time())
            is_task = hasattr(get, 'is_task') and get.is_task == 1
            # 检查上次执行时间（仅对计划任务生效）
            if is_task and os.path.exists(last_detection_file):
                try:
                    with open(last_detection_file, 'r') as f:
                        # 添加文件锁
                        fcntl.flock(f, fcntl.LOCK_SH)
                        try:
                            last_detection_data = json.load(f)
                        finally:
                            fcntl.flock(f, fcntl.LOCK_UN)
                            
                    last_detection_time = last_detection_data.get('time', 0)
                    # 检查是否需要执行 (6小时 = 21600秒)
                    if (current_time - last_detection_time) < 21600:
                        return public.returnMsg(True, '距离上次扫描时间不足6小时，跳过本次扫描')
                except Exception as e:

                    return {
                        'status': False,
                        'msg': "扫描过程中发生错误: {}".format(str(e)),
                        'detected': []
                    }
            
            # 更新执行时间（提前写入，防止长时间执行导致多次触发）
            if is_task:
                try:
                    with open(last_detection_file, 'w') as f:
                        fcntl.flock(f, fcntl.LOCK_EX)
                        try:
                            json.dump({'time': current_time}, f)
                        finally:
                            fcntl.flock(f, fcntl.LOCK_UN)
                except Exception as e:
                    return {
                        'status': False,
                        'msg': "扫描过程中发生错误: {}".format(str(e)),
                        'detected': []
                    }

            # 获取新增或修改的文件
            new_files = self.get_new_files()

            # 对新增文件进行木马查杀
            detected_webshells = self.scan_suspicious_files(new_files)


            # 告警配置
            return {
                'status': True,
                'msg': "扫描完成，发现{}个可疑文件".format(len(detected_webshells)),
                'detected': detected_webshells
            }
        except Exception as e:
            # public.print_log("Error in webshell_file: {}".format(str(e)))
            return {
                'status': False,
                'msg': "扫描过程中发生错误: {}".format(str(e)),
                'detected': []
            }

    def load_last_scan(self) -> Dict:
        """加载上次扫描结果
        @time: 2025-02-19
        @return: <dict> 上次扫描结果
        """
        if not os.path.exists(self.__last_scan):
            return {}
        try:
            with open(self.__last_scan, 'r') as f:
                return json.load(f)
        except Exception as e:
            # logging.error("Error loading last scan: {}".format(str(e)))
            return {}

    def save_current_scan(self, scan_data: Dict) -> None:
        """保存当前扫描结果
        @time: 2025-02-19
        @param scan_data: 扫描结果
        @return: <None> 保存当前扫描结果
        """
        try:
            # 读取上次的扫描结果
            last_scan_info = self.load_last_scan()
            # last_total_files = last_scan_info.get('total_files', 0)
            # 添加更多元数据
            scan_data.update({
                'scan_version': '1.0',
                'scan_timestamp': time.time(),
                'scan_date': time.strftime("%Y-%m-%d %H:%M:%S"),
                # 'total_dirs': len(scan_data['directories']),
                'total_files': scan_data.get('total_files', 0),  # 单次扫描文件总数
            })

            # 确保目录存在
            scan_dir = os.path.dirname(self.__last_scan)
            if not os.path.exists(scan_dir):
                os.makedirs(scan_dir)

            # 保存当前扫描结果
            with open(self.__last_scan, 'w') as f:
                json.dump(scan_data, f, indent=4)

            # # 创建备份（可选）
            # backup_path = "{self.__last_scan}.{time.strftime('%Y%m%d_%H%M%S')}.bak"
            # with open(backup_path, 'w') as f:
            #     json.dump(scan_data, f, indent=4)

        except Exception as e:
            # logging.error("Error saving current scan: {}".format(str(e)))
            pass

    def load_dir_record(self) -> Dict:
        """加载目录记录
        @time: 2025-02-19
        @return: 目录记录信息
        """
        try:
            if os.path.exists(self.__dir_record):
                with open(self.__dir_record, 'r') as f:
                    return json.load(f)
            return {'directories': {}, 'last_update': 0}
        except Exception as e:
            # logging.error("加载目录记录失败: {}".format(str(e)))
            return {'directories': {}, 'last_update': 0}

    def save_dir_record(self, record_data: Dict) -> None:
        """保存目录记录
        @time: 2025-02-19
        @param record_data: 目录记录数据
        """
        try:
            record_data['last_update'] = time.time()
            with open(self.__dir_record, 'w') as f:
                json.dump(record_data, f, indent=4)
        except Exception as e:
            # logging.error("保存目录记录失败: {}".format(str(e)))
            pass

    # 获取木马文件检测结果
    def get_webshell_result(self, get):
        """
            @name 木马隔离文件
            @author wpl@bt.cn
            @time 2025-02-14
            @return list 木马文件列表
        """
        try:
            # 埋点
            public.set_module_logs("safe_detect", "get_webshell_result")
            # 获取上次扫描信息
            last_scan_info = self.load_last_scan()
            last_scan_stats = {
                'scan_time': time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(last_scan_info.get('scan_timestamp', 0))),
                'total_files': last_scan_info.get('total_files', 0)
                # 'total_dirs': last_scan_info.get('total_dirs', 0)
            }

            # 确定时间范围
            current_time = time.time()
            time_range = None
            if hasattr(get, 'day'):
                if get.day == '1':
                    time_range = current_time - 24 * 3600  # 今天（24小时内）
                elif get.day == '7':
                    time_range = current_time - 7 * 24 * 3600  # 近7天
                elif get.day == '30':
                    time_range = current_time - 30 * 24 * 3600  # 近30天

            ret = []
            risk_stats = {0: 0, 1: 0, 2: 0}  # 风险等级统计
            processed_stats = {0: 0, 1: 0}  # 处理状态统计

            # 读取总日志文件
            log_path = os.path.join(self.__log_dir, "detection_all.log")
            if not os.path.exists(log_path):
                return {
                    'status': True,
                    'msg': "日志文件不存在",
                    'detected': [],
                    'last_scan_time': last_scan_stats['scan_time'],
                    'total_scanned_files': last_scan_stats['total_files'],
                    'risk_stats': risk_stats,
                    'processed_stats': processed_stats
                }



            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f.readlines():
                    line = line.strip()
                    if not line: continue

                    try:
                        # 解析日志行
                        parts = line.split('|')
                        if len(parts) >= 9:
                            file_info = {
                                'filename': parts[0],
                                'filepath': parts[1],
                                'threat_type': parts[2],
                                'md5': parts[3],
                                'risk_level': int(parts[4]),
                                'time': parts[5],
                                'quarantined': parts[6].lower() == 'true',
                                'rule': parts[7],
                                'processed': int(parts[8])
                            }

                            # 时间范围筛选
                            if time_range:
                                log_time = time.mktime(time.strptime(file_info['time'], "%Y-%m-%d %H:%M:%S"))
                                if log_time < time_range:
                                    continue

                            # ... existing code for risk level description ...
                            file_info['risk_level_desc'] = {
                                0: '低危',
                                1: '中危',
                                2: '高危'
                            }.get(file_info['risk_level'], '未知')

                            # ... existing code for filtering ...
                            if hasattr(get, 'risk_level') and str(file_info['risk_level']) != str(get.risk_level):
                                continue

                            if hasattr(get, 'processed'):
                                if str(file_info['processed']) != str(get.processed):
                                    continue
                            else:
                                if file_info['processed'] != 0:
                                    continue

                            # 更新统计信息
                            risk_stats[file_info['risk_level']] += 1
                            processed_stats[file_info['processed']] += 1

                            ret.append(file_info)
                    except Exception as e:
                        # logging.error("Error parsing log line: {}".format(str(e)))
                        continue

            # ... existing code ...
            ret.sort(key=lambda x: x['time'], reverse=True)

            return {
                'status': True,
                'msg': "获取成功",
                'detected': ret,
                'last_scan_time': last_scan_stats['scan_time'],
                'total_scanned_files': last_scan_stats['total_files'],
                'total_detected': len(ret),
                'risk_stats': risk_stats,
                'processed_stats': processed_stats
            }

        except Exception as e:
            # logging.error("Error in webshell_file: {}".format(str(e)))
            return {
                'status': True,
                'msg': "扫描过程中发生错误: {}".format(str(e)),
                'detected': [],
                'last_scan_time': '',
                'total_scanned_files': 0,
                'total_detected': 0,
                'risk_stats': risk_stats,
                'processed_stats': processed_stats
            }

    # 开启自动检测服务 每两小时执行一次

    # 配置获取
    def get_config(self, get) -> Dict:
        """获取配置信息
        @time: 2025-02-19
        @return: <dict> 配置信息
        """
        try:
            return {
                'status': True,
                'msg': '获取成功',
                'data': {
                    # 'monitor_dirs': self.__config.config.get('monitor_dirs', []),
                    # 'supported_exts': self.__config.config.get('supported_exts', []),
                    'scan_interval': self.__config.config.get('scan_interval', 1),
                    # 'max_threads': self.__config.config.get('max_threads', 4),
                    # 'log_level': self.__config.config.get('log_level', 'INFO'),
                    # 'exclude_dirs': self.__config.config.get('exclude_dirs', []),
                    # 'max_file_size': self.__config.config.get('max_file_size', 5242880),
                    # 'scan_delay': self.__config.config.get('scan_delay', 0.1),
                    # 'skipped_dirs': self.__config.config.get('skipped_dirs', {}),
                    # 'max_files_per_dir': self.__config.config.get('max_files_per_dir', 10000),
                    'quarantine': self.__config.config.get('quarantine', False),
                    'alertable': self.__config.config.get('alertable', {}),
                    'dynamic_detection': self.__config.config.get('dynamic_detection', True)
                }
            }
        except Exception as e:
            # logging.error("Error getting config: {}".format(str(e)))
            return {
                'status': False,
                'msg': "获取配置失败: {}".format(str(e)),
                'data': {}
            }

    def set_config(self, get):
        """修改配置信息
        @time: 2025-02-19
        @param get.quarantine: 是否隔离
        @param get.monitor_dirs: 监控目录列表
        @param get.supported_exts: 支持的文件扩展名列表
        """
        try:
            # 定义可修改的配置项及其验证规则
            config_rules = {
                'quarantine': {
                    'validator': lambda x: str(x).lower() in ('true', 'false'),
                    'converter': lambda x: str(x).lower() == 'true',
                    'error_msg': "quarantine 参数必须是 'true' 或 'false'",
                    'success_msg': lambda x: "文件拦截功能已{}".format("开启" if x else "关闭")
                },
                'dynamic_detection': {
                    'validator': lambda x: str(x).lower() in ('true', 'false'),
                    'converter': lambda x: str(x).lower() == 'true',
                    'error_msg': "dynamic_detection 参数必须是 'true' 或 'false'",
                    'success_msg': lambda x: "动态查杀功能已{}".format("开启" if x else "关闭")
                },
                'monitor_dirs': {
                    'validator': lambda x: isinstance(x, str) and x.strip(),
                    'converter': lambda x: x.strip().split('\n'),
                    'error_msg': 'monitor_dirs 格式错误，请确保每行一个目录路径',
                    'success_msg': lambda x: "监控目录已更新，当前共{}个目录".format(len(x))
                },
                'supported_exts': {
                    'validator': lambda x: isinstance(x, str) and x.strip(),
                    'converter': lambda x: [ext.strip() if ext.strip().startswith('.') else '.{}'.format(ext.strip())
                                            for ext in x.strip().split('\n')],
                    'error_msg': 'supported_exts 格式错误，请确保每行一个扩展名',
                    'success_msg': lambda x: "监控文件类型已更新，当前支持{}种扩展名".format(len(x))
                }
            }

            # 记录修改项
            changed = False
            success_messages = []

            # 处理每个配置项
            for key, rule in config_rules.items():
                # 获取表单数据
                value = getattr(get, key, None)
                if value is not None:
                    try:
                        # 验证参数
                        if not rule['validator'](value):
                            return public.returnMsg(False, rule['error_msg'])

                        # 转换值
                        new_value = rule['converter'](value)

                        # 对目录和扩展名进行额外验证
                        if key == 'monitor_dirs':
                            # 过滤掉空行和不存在的目录
                            new_value = [path for path in new_value if path and os.path.exists(path)]
                            if not new_value:
                                return public.returnMsg(False, '未提供有效的监控目录路径')

                        elif key == 'supported_exts':
                            # 过滤掉空行和重复的扩展名
                            new_value = list(set(ext for ext in new_value if ext))
                            if not new_value:
                                return public.returnMsg(False, '未提供有效的文件扩展名')

                        # 检查值是否发生变化
                        old_value = self.__config.config.get(key)
                        if new_value != old_value:
                            self.__config.config[key] = new_value
                            changed = True
                            # 添加成功消息
                            success_messages.append(rule['success_msg'](new_value))

                    except Exception as e:
                        return public.returnMsg(False, '处理 {} 参数时出错: {}'.format(key, str(e)))

            # 如果有修改，保存配置
            if changed:
                try:
                    self.__config.save_config()
                    # 返回所有成功消息
                    return public.returnMsg(True, '设置成功：{}'.format('；'.join(success_messages)))
                except Exception as e:
                    return public.returnMsg(False, '保存配置文件失败: {}'.format(str(e)))
            else:
                return public.returnMsg(False, '未检测到配置变更')

        except Exception as e:
            # logging.error("Error in set_config: {}".format(str(e)))
            return public.returnMsg(False, '修改配置失败: {}'.format(str(e)))

    # 开启恶意文件检测
    def start_malware_detection(self):

        pass

    def start_service(self, get):
        '''
            @time: 2025-02-19
            @name 启动服务
            @return dict
        '''
        if self.get_service_status2(): return public.returnMsg(False, '服务已启动!')
        self.wrtie_init()
        shell_info = '''
            # 填写启动服务脚本
        '''
        init_file = '/etc/init.d/bt_cloud_safe'
        public.WriteFile('/www/server/panel/class/projectModel/bt_cloud_safe', shell_info)
        time.sleep(0.3)
        public.ExecShell("{} start".format(init_file))
        if self.get_service_status2():
            # public.WriteLog('文件监控','启动服务')
            return public.returnMsg(True, '启动成功!')
        return public.returnMsg(False, '启动失败!')

    def stop_service(self, get):
        '''
            @time: 2025-02-19
            @name 停止服务
            @return dict
        '''
        if not self.get_service_status2(): return public.returnMsg(False, '服务已停止!')
        init_file = '/etc/init.d/bt_cloud_safe'
        public.ExecShell("{} stop".format(init_file))
        time.sleep(0.3)
        if not self.get_service_status2():
            public.WriteLog('木马云查杀', '停止服务')
            return public.returnMsg(True, '停止成功!')
        return public.returnMsg(False, '停止失败!')

    def convert_to_bool(self, value):
        if isinstance(value, bool):
            return value
        elif isinstance(value, str):
            lower_value = value.lower()
            if lower_value in ['true', '1', 'yes']:
                return True
            elif lower_value in ['false', '0', 'no']:
                return False
        return None

    # 告警配置
    def set_alarm_config(self, get):
        '''
            @time: 2025-02-19
            @name 设置告警配置
                - 支持告警方式:邮件、企业微信机器人、钉钉机器人、飞书机器人
                - 支持功能:木马查杀
                - 支持频率:10分钟内,仅限告警一次
            @param get.status: 是否开启[用户可设置]
            @param get.safe_type: 告警功能,目前支持webshell木马[用户可设置]
            @param get.sender: 告警方式[用户可设置]
            @param get.interval: 告警间隔 默认3小时仅限告警一次
            @param get.time_rule: 告警时间规则 默认10分钟内仅限告警一次
            @param get.number_rule: 告警数量规则 默认一天仅限告警20次
            @return dict
        '''
        try:
            # 参数验证
            if not hasattr(get, 'status') or not hasattr(get, 'safe_type') or not hasattr(get, 'sender'):
                return public.returnMsg(False, '参数错误: 必须提供 status, safe_type 和 sender')

            # 转换并验证状态值
            try:
                # status = bool(get.status)
                status = self.convert_to_bool(get.status)
            except:
                return public.returnMsg(False, 'status 必须为布尔值')
            # public.print_log("|====status:{}".format(status))

            # 验证告警功能
            supported_types = ['webshell']
            if get.safe_type not in supported_types:
                return public.returnMsg(False, '请勾选支持告警类型!')

            # 验证告警方式
            # supported_senders = ['mail', 'wx_account', 'dingding', 'weixin', 'feishu']
            sender_list = get.sender.split(',')
            # for sender in sender_list:
            #     if sender not in supported_senders:
            #         return public.returnMsg(False, '不支持的告警方式: {}，支持的方式: {}'.format(sender, ",".join(supported_senders)))

            # 获取现有配置
            current_config = self.__config.config.get('alertable', {})

            # 构造告警配置
            alert_data = {
                "status": status,
                "safe_type": [get.safe_type],
                "sender": sender_list,
                # 保持其他配置项不变或使用默认值
                "interval": current_config.get('interval', 10800),  # 3小时
                "time_rule": current_config.get('time_rule', {"send_interval": 600}),  # 10分钟
                "number_rule": current_config.get('number_rule', {"day_num": 20})  # 每天20次
            }

            # 保存配置
            from mod.base.push_mod.safe_mod_push import SafeCloudTask
            res = SafeCloudTask.set_push_conf(alert_data)
            # public.print_log("|=======res:{}".format(res))

            if not res:
                # 更新本地配置
                self.__config.config['alertable'] = alert_data
                self.__config.save_config()
                return public.returnMsg(True, '告警配置设置成功')
            else:
                return public.returnMsg(False, '告警配置设置失败: {}'.format(res))

        except Exception as e:
            return public.returnMsg(False, '设置告警配置时发生错误: {}'.format(str(e)))

    # 获取告警配置
    def get_alarm_config(self, get):
        '''
            @time: 2025-02-19
            @name 获取告警配置
            @return dict
        '''

        pass
    def scan_suspicious_files(self, file_list: List[str]) -> List[str]:
        """对文件列表进行木马查杀
        @time: 2025-02-19
        @param file_list: 文件列表
        @return: <list> 可疑文件列表
        """
        detected_webshells = []
        try:
            for file_path in file_list:
                try:
                    is_suspicious, rule = self.scan_file(file_path)
                    if is_suspicious:
                        # 如果文件是可疑的，判断是否需要隔离处理
                        if self.__config.config['quarantine']:
                            self.handle_suspicious_file(file_path, rule)
                        else:
                            self.write_detection_log(file_path, rule, self.__config.config['quarantine'])
                        
                        detected_webshells.append(file_path)
                except Exception as e:
                    # logging.error("Error scanning file {}: {}".format(file_path, str(e)))
                    continue
                    
            # 如果检测到木马文件，发送批量告警
            if detected_webshells:
                self.send_webshell_batch_alert(detected_webshells)
                
        except Exception as e:
            # logging.error("Error in scan_suspicious_files: {}".format(str(e)))
            pass

        return detected_webshells

    def send_webshell_batch_alert(self, file_paths: List[str]) -> None:
        """发送木马检测批量告警
        @param file_paths: 木马文件路径列表
        @return: None
        """
        try:
            # 检查是否有文件需要告警
            if not file_paths:
                return
                
            # 检查告警配置是否已启用
            alert_config = self.__config.config.get('alertable', {})
            if not alert_config.get('status', False) or not alert_config.get('sender'):
                logging.info("告警功能未启用或未配置告警方式，跳过告警发送")
                return

            # 构造告警消息
            alert_msg = [
                "【恶意文件检测】检测到服务器被恶意植入木马文件，请进入面板，点击首页-安全风险，进行查看",
                "已检测出木马文件数量为{}".format(len(file_paths)),
                "木马文件路径如下："
            ]
            
            # 添加所有文件路径
            alert_msg.extend(file_paths)

            # 发送告警消息
            from mod.base.push_mod.safe_mod_push import SafeCloudTask
            try:
                SafeCloudTask.do_send(
                    msg_list=alert_msg,
                    wx_msg="检测到{}个木马文件".format(len(file_paths)),
                    wx_thing_type="堡塔云安全中心-木马告警"
                )
                # public.print_log("木马告警发送成功，共{}个文件".format(len(file_paths)))
            except Exception as e:
                # public.print_log("木马告警发送失败: {}".format(str(e)))
                pass

        except Exception as e:
            # public.print_log("执行木马告警时发生错误: {}".format(str(e)))
            pass

    def test_alarm_send(self, get) -> dict:
        """测试告警发送
        @time: 2025-02-19
        @return dict
        """
        try:
            # 检查告警配置是否已启用
            alert_config = self.__config.config.get('alertable', {})
            if not alert_config.get('status', False):
                return public.returnMsg(False, '告警功能未启用，请先启用告警功能')

            if not alert_config.get('sender'):
                return public.returnMsg(False, '未配置告警方式，请先配置告警方式')

            # 构造测试消息
            test_msg = [
                "【安全告警测试】",
                "这是一条测试消息，用于验证告警配置是否正常。",
                "当前告警方式: {}".format(','.join(alert_config['sender'])),
                "发送时间: {}".format(time.strftime('%Y-%m-%d %H:%M:%S'))
            ]

            # 发送测试消息
            from mod.base.push_mod.safe_mod_push import SafeCloudTask
            try:
                SafeCloudTask.do_send(
                    msg_list=test_msg,
                    wx_msg="安全告警测试消息",
                    wx_thing_type="堡塔云安全中心-测试告警"
                )
                return public.returnMsg(True, '测试消息发送成功')
            except Exception as e:
                return public.returnMsg(False, '测试消息发送失败: {}'.format(str(e)))

        except Exception as e:
            return public.returnMsg(False, '执行告警测试时发生错误: {}'.format(str(e)))


    def GetCheckUrl(self):
        '''
            @time: 2025-02-19
            @name 获取云端URL地址
            @author lkq<2022-4-12>
            @return URL
        '''
        try:

            ret = requests.get('http://www.bt.cn/checkWebShell.php').json()
            # public.print_log("|====ret:".format(ret))
            if ret['status']:
                return ret['url']
            return False
        except:
            return False

    def ReadFile(self, filepath, mode='r'):
        '''
            @time: 2025-02-19
            @name 读取文件内容
            @param filepath 文件路径
            @return 文件内容
        '''
        import os
        if not os.path.exists(filepath): return False
        try:
            fp = open(filepath, mode)
            f_body = fp.read()
            fp.close()
        except Exception as ex:
            if sys.version_info[0] != 2:
                try:
                    fp = open(filepath, mode, encoding="utf-8")
                    f_body = fp.read()
                    fp.close()
                except Exception as ex2:
                    return False
            else:
                return False
        return f_body

    def test_file(self, get):
        '''
            @time: 2025-02-19
            @name 测试文件是否为木马
            @param get.filepath 要检测的文件路径
            @return dict
        '''
        try:
            # 验证参数
            if not hasattr(get, 'filepath'):
                return public.returnMsg(False, '请提供要检测的文件路径!')

            filepath = get.filepath
            if not os.path.exists(filepath):
                return public.returnMsg(False, '文件不存在: {}'.format(filepath))

            # 获取文件大小
            file_size = os.path.getsize(filepath)
            if file_size > 1024000:  # 1MB限制
                return public.returnMsg(False, '文件大小超过限制(1MB)')

            # 获取云端检测URL
            url = self.GetCheckUrl()
            if not url:
                return public.returnMsg(False, '获取云端检测地址失败')

            # 进行云端检测
            try:
                # 准备上传数据
                upload_data = {
                    'inputfile': self.ReadFile(filepath),
                    'md5': self.FileMd5(filepath)
                }

                # 发送检测请求
                upload_res = requests.post(url, upload_data, timeout=20).json()

                # 处理响应结果
                if upload_res['msg'] == 'ok':
                    is_webshell = upload_res['data']['data']['level'] == 5
                    return {
                        'status': True,
                        'msg': '检测完成',
                        'data': {
                            'filepath': filepath,
                            'is_webshell': is_webshell,
                            'level': upload_res['data']['data']['level'],
                            'md5': upload_data['md5']
                        }
                    }
                else:
                    return public.returnMsg(False, '云端检测失败: {}'.format(upload_res['msg']))

            except Exception as e:
                return public.returnMsg(False, '云端检测请求失败: {}'.format(str(e)))

        except Exception as e:
            # logging.error("Error in test_file: {}".format(str(e)))
            return public.returnMsg(False, '测试过程发生错误: {}'.format(str(e)))
    
    # 移动到回收站
    def Mv_Recycle_bin(self, path):
        if not os.path.islink(path):
            path = os.path.realpath(path)
        rPath = public.get_recycle_bin_path(path)
        # public.print_log("|=========================================|")
        # public.print_log("|============rPath:{}".format(rPath))
        # public.print_log("|============path:{}".format(path))
        # public.print_log("|=========================================|")
        rFile = os.path.join(rPath, path.replace('/', '_bt_') + '_t_' + str(time.time()))
        try:
            import shutil
            shutil.move(path, rFile)
            public.WriteLog('TYPE_FILE', 'FILE_MOVE_RECYCLE_BIN', (path,))
            return True
        except:
            public.WriteLog(
                'TYPE_FILE', 'FILE_MOVE_RECYCLE_BIN_ERR', (path,))
            return False

    def deal_webshell_file(self, get):
        """
        @name 批量处理恶意文件（删除文件及对应日志）
        @author wpl
        @param file_list: [{"filepath": "/path/file.php", "md5": "a1b2c3..."}, ...]
        @param action_type: "delete"  # 预留其他操作类型
        @return 处理结果及详细报告
        """
        result = {
            "status": True,
            "success": [],
            "failed": [],
            "total": 0,
            "log_modified": False,
            "log_entries_removed": []  # 新增：记录被删除的日志条目
        }

        try:
            # 参数校验
            if not hasattr(get, 'file_list'):
                return public.returnMsg(False, "缺少必要参数: file_list")
            
            try:
                if isinstance(get.file_list, str):
                    file_list = json.loads(get.file_list)
                else:
                    file_list = get.file_list
            except Exception as e:
                return public.returnMsg(False, "文件列表解析失败: {}".format(str(e)))

            if not isinstance(file_list, list) or len(file_list) == 0:
                return public.returnMsg(False, "文件列表格式错误")

            result['total'] = len(file_list)

            # 校验文件列表格式
            valid_files = []
            for item in file_list:
                if not isinstance(item, dict) or 'filepath' not in item or 'md5' not in item:
                    result['failed'].append({
                        "filepath": str(item.get('filepath', '')),
                        "md5": str(item.get('md5', '')),
                        "reason": "参数格式错误"
                    })
                    continue
                valid_files.append(item)
            
            if not valid_files:
                return public.returnMsg(False, "无有效待处理文件")

            # 首先处理日志文件
            log_path = os.path.join(self.__log_dir, "detection_all.log")
            if os.path.exists(log_path):
                try:
                    # 使用文件锁保证原子操作
                    with open(log_path, 'r+') as f:
                        fcntl.flock(f, fcntl.LOCK_EX)
                        try:
                            # 读取全部日志
                            remaining_lines = []
                            removed_lines = []
                            
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                
                                # 解析日志行
                                parts = line.split('|')
                                if len(parts) < 9:
                                    remaining_lines.append(line + '\n')
                                    continue
                                    
                                log_filepath = parts[1]
                                log_md5 = parts[3].lower()
                                
                                # 检查是否需要删除该记录
                                should_remove = False
                                for file_info in valid_files:
                                    target_path = os.path.normpath(file_info['filepath'])
                                    target_md5 = file_info['md5'].lower()
                                    
                                    if (os.path.normpath(log_filepath) == target_path and 
                                        log_md5 == target_md5):
                                        should_remove = True
                                        removed_lines.append({
                                            'filepath': log_filepath,
                                            'md5': log_md5,
                                            'full_log': line
                                        })
                                        break
                                        
                                if not should_remove:
                                    remaining_lines.append(line + '\n')
                            
                            # 更新日志文件
                            f.seek(0)
                            f.writelines(remaining_lines)
                            f.truncate()
                            
                            result['log_modified'] = True
                            result['log_entries_removed'] = removed_lines
                            
                        finally:
                            fcntl.flock(f, fcntl.LOCK_UN)
                            
                except Exception as e:
                    # logging.error("处理日志文件时出错: {}".format(str(e)))
                    result['log_modified'] = False

            # 处理文件删除
            processed_files = set()  # 用于去重 (filepath, md5)
            for file_info in valid_files:
                filepath = file_info['filepath']
                target_md5 = file_info['md5'].lower()

                # 去重检查
                unique_key = (os.path.normpath(filepath), target_md5)
                if unique_key in processed_files:
                    result['failed'].append({
                        "filepath": filepath,
                        "md5": target_md5,
                        "reason": "重复提交"
                    })
                    continue
                processed_files.add(unique_key)

                # 尝试删除文件（如果存在）
                try:
                    if os.path.exists(filepath):
                        # 校验当前文件MD5
                        try:
                            with open(filepath, 'rb') as f:
                                current_md5 = hashlib.md5(f.read()).hexdigest().lower()
                        except Exception as e:
                            result['failed'].append({
                                "filepath": filepath,
                                "md5": target_md5,
                                "reason": "MD5计算失败: {}".format(str(e))
                            })
                            continue

                        # MD5匹配校验
                        if current_md5 != target_md5:
                            result['failed'].append({
                                "filepath": filepath,
                                "md5": target_md5,
                                "reason": "MD5不匹配(当前:{})".format(current_md5)
                            })
                            continue

                        # 执行文件删除
                        try:
                            # os.remove(filepath)
                            # 目前采用转移到回收站，不直接删除，避免删除了正常文件
                            self.Mv_Recycle_bin(filepath)
                            result['success'].append({
                                "filepath": filepath,
                                "md5": target_md5
                            })
                        except Exception as e:
                            result['failed'].append({
                                "filepath": filepath,
                                "md5": target_md5,
                                "reason": "删除失败: {}".format(str(e))
                            })
                    else:
                        # 文件不存在也记录到成功列表，因为目标是移除该文件
                        result['success'].append({
                            "filepath": filepath,
                            "md5": target_md5,
                            "note": "文件已不存在"
                        })

                except Exception as e:
                    result['failed'].append({
                        "filepath": filepath,
                        "md5": target_md5,
                        "reason": "处理过程出错: {}".format(str(e))
                    })

            return {
                "status": True,
                "msg": "处理完成",
                "data": result
            }

        except Exception as e:
            error_msg = "处理过程中发生严重错误: {}".format(str(e))
            # logging.exception(error_msg)
            return {
                "status": False,
                "msg": error_msg,
                "data": result
            }

    def get_safecloud_list(self, get) -> dict:
        # 获取云安全检测 查杀数量
        # 恶意文件检测、漏洞扫描、首页风险
        # 首页风险：/www/server/panel/data/warning/resultresult.json  读取risk里的status为false的
        # 漏洞扫描：/www/server/panel/data/scanning.json，读取loophole_num 
        # 恶意文件检测：/www/server/panel/data/safeCloud/log/detection_all.log 只统计高危
        # 总数  累加 
        """获取云安全检测统计数据
        @return: dict {
            'total': 总风险数,
            'malware': 恶意文件检测数量,
            'vulnerability': 网站漏洞检测数量,
            'security': 安全风险检测数量,
            'update_time': 更新时间
        }
        """
        try:
            result = {
                'total': 0,          # 总风险数
                'malware': 0,        # 恶意文件检测数量
                'vulnerability': 0,   # 网站漏洞检测数量
                'security': 0,        # 安全风险检测数量
                'security_score': 100,        # 默认安全得分为100
                'update_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # 1. 统计首页风险（security状态为false的数量）
            security_file = '/www/server/panel/data/warning/resultresult.json'
            try:
                if os.path.exists(security_file):
                    security_data = json.loads(public.readFile(security_file))
                    if isinstance(security_data, dict):
                        # 获取首页风险检测得分
                        result['security_score'] = int(security_data.get('score', 100))
                        # 获取检查时间
                        result['check_time'] = security_data.get('check_time', '')
                        # 统计risk中status为false的项目数量
                        if 'risk' in security_data:
                            result['security'] = sum(
                                1 for item in security_data['risk'] 
                                if isinstance(item, dict) and item.get('status') is False
                            )
            except Exception as e:
                # logging.error("读取安全风险数据失败: {}".format(str(e)))
                pass
                
            # 2. 统计漏洞扫描数量
            scanning_file = '/www/server/panel/data/scanning.json'
            try:
                if os.path.exists(scanning_file):
                    with open(scanning_file, 'r') as f:
                        scanning_data = json.load(f)
                        result['vulnerability'] = int(scanning_data.get('loophole_num', 0))
            except Exception as e:
                # logging.error("读取漏洞扫描数据失败: {}".format(str(e)))
                pass
                
            # 3. 统计恶意文件检测数量（高危）
            detection_log = '/www/server/panel/data/safeCloud/log/detection_all.log'
            try:
                if os.path.exists(detection_log):
                    with open(detection_log, 'r') as f:
                        # 读取所有行
                        high_risk_count = 0
                        for line in f:
                            try:
                                if line.strip():
                                    parts = line.strip().split('|')
                                    if len(parts) >= 9:
                                        # 假设风险等级在第5个字段，高危为2
                                        risk_level = parts[4]
                                        if risk_level == '2':  # 高危
                                            high_risk_count += 1
                            except Exception as e:
                                continue
                        result['malware'] = high_risk_count
            except Exception as e:
                # logging.error("读取恶意文件检测数据失败: {}".format(str(e)))
                pass
                
            # 计算总数
            result['total'] = (
                result['security'] + 
                result['vulnerability'] + 
                result['malware']
            )
            
            return {
                'status': True,
                'msg': '获取成功',
                'data': result
            }
            
        except Exception as e:
            # logging.error("获取安全检测统计失败: {}".format(str(e)))
            return {
                'status': False,
                'msg': '获取统计数据失败: {}'.format(str(e)),
                'data': {
                    'total': 0,
                    'malware': 0,
                    'vulnerability': 0,
                    'security': 0,
                    'security_score': 100,
                    'update_time': time.strftime('%Y-%m-%d %H:%M:%S')
                }
            }
    
    def get_security_logs(self, get) -> dict:
        """获取安全日志统计,功能：首页风险、漏洞扫描、恶意文件检测
        @time: 2025-02-24
        @return: dict 安全日志统计信息
        """
        try:
            result = {
                'home_risks': {
                    'count': 0,
                    'score': 0,
                    'check_time': '',
                    'items': [] # 风险项   
                },
                'vulnerabilities': {
                    'site_count': 0,     # 总扫描站点数
                    'risk_count': 0,     # 风险数量
                    'scan_time': '',     # 最近扫描时间
                    'items': []          # 风险项
                },
                'malware': {
                    'count': 0,
                    'last_scan_time': '',
                    'total_scanned': 0,
                    'risk_stats': {},
                    'items': [] # 风险项
                },
                'total': 0,
                'update_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }

            # 1. 读取首页风险
            try:
                risk_file = '/www/server/panel/data/warning/resultresult.json'
                if os.path.exists(risk_file):
                    with open(risk_file, 'r') as f:
                        risk_data = json.load(f)
                        
                        # 获取风险得分和检测时间
                        result['home_risks'].update({
                            'score': risk_data.get('score', 0),
                            'check_time': risk_data.get('check_time', '')
                        })
                        
                        # 获取风险项列表
                        if 'risk' in risk_data:
                            risk_items = []
                            for item in risk_data['risk']:
                                if not isinstance(item, dict):
                                    continue
                                    
                                # 只收集状态为 False（有风险）的项
                                if item.get('status', True) is False:
                                    risk_items.append({
                                        'title': item.get('title', '未知风险'),       # 风险标题
                                        'ps': item.get('ps', ''),                    # 风险备注
                                        'level': item.get('level', 0),               # 风险等级
                                        'ignore': item.get('ignore', False),         # 是否忽略
                                        'msg': item.get('msg', ''),                  # 风险描述
                                        'tips': item.get('tips', []),                # 温馨提示
                                        'remind': item.get('remind', ''),            # 解决方案
                                        'check_time': item.get('check_time', 0)      # 检测时间
                                    })
                            
                            result['home_risks']['items'] = risk_items
                            result['home_risks']['count'] = len(risk_items)
            except Exception as e:
                # logging.error("读取首页风险数据失败: {}".format(str(e)))
                pass


            # 2. 读取漏洞扫描
            try:
                vuln_file = '/www/server/panel/data/scanning.json'
                if os.path.exists(vuln_file):
                    with open(vuln_file, 'r') as f:
                        vuln_data = json.load(f)
                        # 获取基础信息
                        result['vulnerabilities']['site_count'] = vuln_data.get('site_num', 0)
                        result['vulnerabilities']['risk_count'] = vuln_data.get('loophole_num', 0)
                        result['vulnerabilities']['scan_time'] = time.strftime(
                            '%Y-%m-%d %H:%M:%S',
                            time.localtime(vuln_data.get('time', 0))
                        )
                        
                        # 获取具体漏洞信息
                        if 'info' in vuln_data:
                            for site in vuln_data['info']:
                                if 'cms' in site:
                                    for cms in site['cms']:
                                        vuln_item = {
                                            'site_name': site.get('name', ''),
                                            'site_path': site.get('path', ''),
                                            'risk_desc': cms.get('ps', ''),
                                            'risk_level': cms.get('dangerous', 0),
                                            'repair': cms.get('repair', '')
                                        }
                                        result['vulnerabilities']['items'].append(vuln_item)
            except Exception as e:
                # logging.error("读取漏洞扫描数据失败: {}".format(str(e)))
                pass

            # 3. 读取恶意文件检测
            try:
                webshell_result = self.get_webshell_result(get)
                if webshell_result.get('status', False):
                    result['malware'] = {
                        'count': webshell_result.get('total_detected', 0),
                        'last_scan_time': webshell_result.get('last_scan_time', ''),
                        'total_scanned': webshell_result.get('total_scanned_files', 0),
                        'risk_stats': webshell_result.get('risk_stats', {}),
                        'items': webshell_result.get('detected', [])
                    }
            except Exception as e:
                # logging.error("读取恶意文件检测数据失败: {}".format(str(e)))
                pass

            # 计算总风险数
            result['total'] = (
                result['home_risks']['count'] +
                result['vulnerabilities']['risk_count'] +
                result['malware']['count']
            )

            return {
                'status': True,
                'msg': '获取成功',
                'data': result
            }

        except Exception as e:
            # logging.error("获取安全日志统计失败: {}".format(str(e)))
            return {
                'status': False,
                'msg': '获取统计数据失败: {}'.format(str(e)),
                'data': result
            }