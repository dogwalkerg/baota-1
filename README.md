# 宝塔 Linux 面板

发布页面地址：https://baota-releases.now.sh

代码仓库：https://github.com/wei/baota/tree/release


## 使用方法

1. 查看最新版本：https://github.com/wei/baota/releases/latest
1. 查看历史版本：https://github.com/wei/baota/releases
1. 查看 `7.4.3` 版本代码：https://github.com/wei/baota/tree/7.4.3
1. 查看 `7.4.2` ~ `7.4.3` 版本代码变动：https://github.com/wei/baota/compare/7.4.2...7.4.3
1. 查看 `class/jobs.py` 历史：https://github.com/wei/baota/commits/release/panel/class/jobs.py
1. 查看 `class/jobs.py` 代码逐行历史：https://github.com/wei/baota/blame/release/panel/class/jobs.py

[![](http://screenshotter.git.ci/screenshot?url=https://baota-releases.now.sh&viewport=750,500)](https://baota-releases.now.sh)


# 下载离线升级包(也可以手动下载上传到服务器/root目下)：
- 宝塔linux面板离线升级(降级)指定版本
  ```bash
   wget -O LinuxPanel.zip http://download.bt.cn/install/update/LinuxPanel-7.9.0.zip
  ```
- 解压文件：
- ```bash
  unzip LinuxPanel.zip
  ```
- 执行面板自带的升级脚本
  ```bash
   cd panel && bash update.sh
  ```
- 删除升级或降级包：
  ```bash
  cd .. && rm -f LinuxPanel.zip && rm -rf panel
  ```
  
