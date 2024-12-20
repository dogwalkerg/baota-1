# coding: utf-8
# -------------------------------------------------------------------
# 宝塔Linux面板
# -------------------------------------------------------------------
# Copyright (c) 2015-2099 宝塔软件(http://bt.cn) All rights reserved.
# -------------------------------------------------------------------
# Author: wzz <wzz@bt.cn>
# -------------------------------------------------------------------

# ------------------------------
# Docker模型
# ------------------------------
import os
import json
import traceback

import docker.errors
import public
from btdockerModel import dk_public as dp
from btdockerModel.dockerBase import dockerBase


class main(dockerBase):

    def docker_client(self, url):
        return dp.docker_client(url)

    # 导出
    def save(self, get):
        """
        :param path 要镜像tar要存放的路径
        :param name 包名
        :param id 镜像
        :param
        :param get:
        :return:
        """
        try:
            if "name" not in get or get.name == "":
                return public.returnMsg(False, "请输入镜像名name或name不能为空!")
            if "path" not in get or get.path == "":
                return public.returnMsg(False, "请输入镜像路径path或path不能为空!")
            if "id" not in get or get.id == "":
                return public.returnMsg(False, "请输入镜像ID或ID不能为空!")

            if "/" in get.name:
                return public.returnMsg(False, "镜像名不能包含 / ")

            if "tar" in get.name:
                filename = '{}/{}'.format(get.path, get.name)
            else:
                filename = '{}/{}.tar'.format(get.path, get.name)

            if not os.path.exists(get.path): os.makedirs(get.path)

            public.writeFile(filename, "")
            with open(filename, 'wb') as f:
                image = self.docker_client(self._url).images.get(get.id)
                print(image)
                for chunk in image.save(named=True):
                    f.write(chunk)
            dp.write_log("镜像 [{}] 导出到 [{}] 成功".format(get.id, filename))
            return public.returnMsg(True, "成功保存到：{}".format(filename))

        except docker.errors.APIError as e:
            if "empty export - not implemented" in str(e):
                return public.returnMsg(False, "不能导出镜像！")
            return public.get_error_info()
        except Exception as e:
            if "Read timed out" in str(e):
                return public.returnMsg(False, "导出镜像失败,连接docker超时,请尝试重启docker后再试!")
            return public.returnMsg(False, "导出镜像失败!  {}".format(e))

    # 导入
    def load(self, get):
        """
        :param path: 需要导入的镜像路径具体到文件名
        :param get:
        :return:
        """
        try:
            if "path" not in get and get.path == "":
                return public.returnMsg(False, "请输入镜像路径!")

            # 2023/12/20 下午 4:12 判断如果path后缀不为.tar则返回错误
            if not get.path.endswith(".tar"):
                return public.returnMsg(False, "导入镜像失败，文件后缀必须为.tar!")

            from btdockerModel.dockerSock import image
            sk_image = image.dockerImage()
            sk_image.load_image(get.path)

            dp.write_log("镜像 [{}] 导入成功!".format(get.path))
            return public.returnMsg(True, "镜像导入成功！{}".format(get.path))
        except Exception as e:
            if "Read timed out" in str(e):
                return public.returnMsg(False, "导出镜像失败,连接docker超时,请尝试重启docker后再试!")
            if "no such file or directory" in str(e):
                return public.returnMsg(False, "导入镜像失败，容器临时目录创建不成功，请检查防护软件是否存在拦截记录!")
            return public.returnMsg(False, "导入镜像失败!  {}".format(e))

    # 列出所有镜像
    def image_list(self, get):
        """
        :param url
        :param get:
        :return:
        """
        from btdockerModel.dockerSock import image
        sk_image = image.dockerImage()
        sk_images_list = sk_image.get_images()

        from btdockerModel.dockerSock import container
        sk_container = container.dockerContainer()
        container_list = sk_container.get_container()

        data = list()
        for image in sk_images_list:
            if image is None: continue

            if not image['RepoTags'] is None and len(image['RepoTags']) != 0:
                for tag in image['RepoTags']:
                    tmp = {
                        "id": image['Id'],
                        "tags": tag,
                        "name": tag,
                        "digest": image['RepoDigests'][0].split("@")[1] if image['RepoDigests'] else "",
                        "time": image['Created'] if type(image['Created']) == int else None,
                        "size": image['Size'],
                        "created_at": image['Created'],
                        "used": 0,
                        "containers": [],
                    }

                    self.structure_images_list(container_list, tmp)
                    data.append(tmp)
            else:
                tmp = {
                    "id": image['Id'],
                    "tags": "<none>",
                    "name": "<none>",
                    "digest": image['RepoDigests'][0].split("@")[1] if image['RepoDigests'] else "",
                    "time": image['Created'] if type(image['Created']) == int else None,
                    "size": image['Size'],
                    "created_at": image['Created'],
                    "used": 0,
                    "containers": [],
                }

                self.structure_images_list(container_list, tmp)
                data.append(tmp)

        return data

    def structure_images_list(self, container_list, image_info):
        '''
            @name
            @author wzz <2024/5/22 下午5:53>
            @param "data":{"参数名":""} <数据类型> 参数描述
            @return dict{"status":True/False,"msg":"提示信息"}
        '''
        try:
            for container in container_list:
                if image_info['id'] in container['ImageID']:
                    image_info['used'] = 1
                    image_info['containers'].append({
                        "container_id": container['Id'],
                        "container_name": dp.rename(container['Names'][0].replace("/", "")),
                    })
        except:
            pass

    def get_image_attr(self, images):
        image = images.list()
        return [i.attrs for i in image]

    def get_logs(self, get):
        import files
        logs_file = get.logs_file
        return public.returnMsg(True, files.files().GetLastLine(logs_file, 20))

    # 构建镜像
    def build(self, get):
        """
        :param path         dockerfile dir
        :param pull         如果引用的镜像有更新自动拉取
        :param tag          标签 jose:v1
        :param data         在线编辑配置
        :param get:
        :return:
        """
        public.writeFile(self._log_path, "开始构建镜像！")
        if not hasattr(get, "pull"):
            get.pull = False

        min_time = None
        if hasattr(get, "data") and get.data:
            min_time = public.format_date("%Y%m%d%H%M")
            get.path = "/tmp/{}/Dockerfile".format(min_time)
            os.makedirs("/tmp/{}".format(min_time), exist_ok=True)
            public.writeFile(get.path, get.data)

        if not os.path.exists(get.path):
            return public.returnMsg(True, "请输入正确的DockerFile路径！")

        try:
            # 2024/1/18 下午 12:05 取get.path的目录
            get.path = os.path.dirname(get.path)
            image_obj, generator = self.docker_client(self._url).images.build(
                path=get.path,
                pull=True if get.pull == "1" else False,
                tag=get.tag,
                forcerm=True
            )

            if min_time is not None:
                public.ExecShell("rm -rf {}".format(get.path))

            dp.log_docker(generator, "Docker 构建任务！")
            dp.write_log("构建镜像 [{}] 成功!".format(get.tag))
            return public.returnMsg(True, "构建镜像成功!")
        except docker.errors.BuildError as e:
            if "TLS handshake timeout" in str(e):
                return public.returnMsg(False, "构建失败!连接超时!")
            return public.returnMsg(False, "构建失败!{}".format(e))
        except docker.errors.APIError as e:
            if "Cannot locate specified Dockerfile" in str(e):
                return public.returnMsg(False, "构建失败!未找到指定的Dockerfile!")
            return public.returnMsg(False, "构建失败!{}".format(e))
        except Exception as e:
            return public.returnMsg(False, "构建失败!{}".format(e))

    # 删除镜像
    def remove(self, get):
        """
        :param url
        :param id  镜像id
        :param name 镜像tag
        :force 0/1 强制删除镜像
        :param get:
        :return:
        """
        try:
            from btdockerModel.dockerSock import image
            sk_image = image.dockerImage()
            image_inspect = sk_image.inspect(get.name)
            if not image_inspect:
                self.docker_client(self._url).images.remove(get.id)
            else:
                self.docker_client(self._url).images.remove(get.name)

            dp.write_log("删除镜像【{}】成功!".format(get.name))
            return public.returnMsg(True, "删除镜像成功!")

        except docker.errors.ImageNotFound as e:
            return public.returnMsg(False, "删除进行失败，镜像可能不存在!")

        except docker.errors.APIError as e:
            if "image is referenced in multiple repositories" in str(e):
                return public.returnMsg(False, "镜像 ID 用在多个镜像中，请强制删除镜像!")
            if ("using its referenced image" in str(e) or
                    "image is being used by stopped container" in str(e) or
                    "image is being used by running container" in str(e)):
                return public.returnMsg(False, "镜像正在使用中，请删除容器后再删除镜像!")

            return public.returnMsg(False, "删除镜像失败!  {}".format(e))
        except Exception as e:
            if "Read timed out" in str(e):
                return public.returnMsg(False, "删除镜像失败,连接docker超时,请尝试重启docker后再试!")
            return public.returnMsg(False, "删除镜像失败!  {}".format(e))

    # 拉取指定仓库镜像
    def pull_from_some_registry(self, get):
        """
        :param name 仓库名
        :param url
        :param image
        :param get:
        :return:
        """
        if not hasattr(get, "_ws"):
            return True

        from btdockerModel import registryModel as dr

        r_info = {
            "name": "docker官方库",
            "reg_name": "docker官方库",
            "url": "docker.io",
            "username": None,
            "password": None,
            "namespace": "library"
        }

        try:
            if get.name != "docker官方库":
                r_info = dr.main().registry_info(get)
                r_info['username'] = public.aes_decrypt(r_info['username'], self.aes_key)
                r_info['password'] = public.aes_decrypt(r_info['password'], self.aes_key)
                login = dr.main().login(self._url, r_info['url'], r_info['username'], r_info['password'])['status']
                if not login:
                    get._ws.send("bt_failed, {}\r\n".format(login['msg']))
                    return login
        except Exception as e:
            get._ws.send("bt_failed, 仓库[ {} ]登录失败,请尝试重新登录此仓库!\r\n".format(get.name))
            return public.returnMsg(False, "bt_failed, 仓库[ {} ]登录失败,请尝试重新登录此仓库!".format(get.name))

        get.username = r_info['username']
        get.password = r_info['password']
        get.registry = r_info['url']
        get.namespace = r_info['namespace']
        get.name = r_info['reg_name'] if "reg_name" in r_info and r_info["reg_name"] != "" else r_info["name"]

        return self.pull(get)

    # 推送镜像到指定仓库
    def push(self, get):
        """
        :param id       镜像ID
        :param url      连接docker的url
        :param tag      标签 镜像名+版本号v1
        :param name     仓库名
        :param get:
        :return:
        """
        if "/" in get.tag:
            return public.returnMsg(False, "推送的镜像不能包含 [/] , 请使用以下格式: image:v1 (镜像名:版本)")

        public.writeFile(self._log_path, "开始推镜像!\n")

        from btdockerModel import registryModel as dr
        r_info = dr.main().registry_info(get)
        r_info['username'] = public.aes_decrypt(r_info['username'], self.aes_key)
        r_info['password'] = public.aes_decrypt(r_info['password'], self.aes_key)

        if get.name == "docker official" and r_info['url'] == "docker.io":
            public.writeFile(self._log_path, "镜像无法推送到 Docker 公共仓库!\n")
            return public.returnMsg(False, "无法推送到 Docker 公共仓库!")

        try:
            login = dr.main().login(self._url, r_info['url'], r_info['username'], r_info['password'])['status']
            if not login:
                return public.returnMsg(False, "仓库[ {} ]登录失败!".format(r_info['url']))

            auth_conf = {
                "username": r_info['username'],
                "password": r_info['password'],
                "registry": r_info['url']
            }

            repository = r_info['url']
            reg_name = r_info['reg_name'] if "reg_name" in r_info and r_info["reg_name"] != "" else r_info["name"]
            image = "{}/{}/{}:{}".format(repository, r_info['namespace'], reg_name, get.tag)

            self.tag(self._url, get.id, image)
            ret = self.docker_client(self._url).images.push(
                repository=image.split(":")[0],
                tag=image.split(":")[1],
                auth_config=auth_conf,
                stream=True
            )

            dp.log_docker(ret, "Image push task")
            # 删除自动打标签的镜像
            get.name = image
            self.remove(get)

        except docker.errors.APIError as e:
            if "invalid reference format" in str(e):
                return public.returnMsg(False, "推送失败, 镜像标签错误, 请输入如: v1.0.1")
            if "denied: requested access to the resource is denied" in str(e):
                return public.returnMsg(False, "推送失败，没有权限推送到这个仓库!")
            return public.returnMsg(False, "推送失败!{}".format(e))

        dp.write_log("镜像 [{}] 推送成功！".format(image))
        return public.returnMsg(True, "推送成功，镜像：{}".format(image))

    def tag(self, url, image_id, tag):
        """
        为镜像打标签
        :param repository   仓库namespace/images
        :param image_id:          镜像ID
        :param tag:         镜像标签jose:v1
        :return:
        """
        image = tag.split(":")[0]
        tag_ver = tag.split(":")[1]
        self.docker_client(url).images.get(image_id).tag(
            repository=image,
            tag=tag_ver
        )
        return public.returnMsg(True, "设置成功！")

    def pull(self, get):
        """
        :param image
        :param url
        :param registry
        :param username 拉取私有镜像时填写
        :param password 拉取私有镜像时填写
        :param get:
        :return:
        """
        get._ws.send("正在拉取镜像,请等待...\r\n")

        import docker.errors
        import time
        time.sleep(0.1)
        get._ws.send("拉取或者搜索镜像中...\r\n")
        try:
            auth_data = {
                "username": get.username,
                "password": get.password,
                "registry": get.registry if get.registry else None
            }
            auth_conf = auth_data if get.username else None

            if get.registry == "docker.io":
                get.image = '{}:latest'.format(get.image) if ':' not in get.image else get.image

            if not hasattr(get, "tag"): get.tag = get.image.split(":")[-1]

            if get.registry != "docker.io":
                get.image = "{}/{}/{}:{}".format(get.registry, get.namespace, get.name, get.image)

            ret = dp.docker_client_low(self._url).pull(
                repository=get.image.split(":")[0],
                auth_config=auth_conf,
                tag=get.tag,
                stream=True
            )

            if not ret:
                get._ws.send("bt_failed, 拉取失败!\r\n")
                return
            last_result = None
            last_progress_str = None
            while True:
                try:
                    output = next(ret)
                    output = json.loads(output)
                    if "errorDetail" in output:
                        if "message" in output['errorDetail']:
                            if ("download failed after" in output['errorDetail']['message'] and
                                    "i/o timeout" in output['errorDetail']['message']):
                                try:
                                    if not os.path.exists("/www/server/panel/config/docker_registry.json"):
                                        public.DownloadFile(
                                            "{}/src/docker_registry.json".format(public.get_url()),
                                            "/www/server/panel/config/docker_registry.json"
                                        )

                                    registry_list = json.loads(
                                        public.readFile("/www/server/panel/config/docker_registry.json"))
                                    if len(registry_list) > 0:
                                        get._ws.send(
                                            "使用默认的镜像站拉取镜像失败!正在为您尝试使用其他的镜像站拉取，请等待...\r\n")
                                        if not "/" in get.image:
                                            get.image = "{}/library/{}".format(registry_list[0].replace("https://", ""),
                                                                               get.image)
                                        else:
                                            get.image = "{}/{}".format(registry_list[0].replace("https://", ""),
                                                                       get.image)

                                        stdout, stderr = public.ExecShell("docker pull {}".format(get.image))
                                        if stderr:
                                            get._ws.send("bt_failed, 拉取镜像失败!\r\n")
                                            return public.returnMsg(False, "拉取镜像失败!")

                                        public.ExecShell("docker tag {} {}".format(get.image, get.image.split("/")[-1]))
                                        public.ExecShell("docker rmi {}".format(get.image))
                                        public.writeFile("/www/server/panel/config/bad_registry.pl", registry_list[0])
                                        get._ws.send(
                                            "bt_successful, 镜像拉取 [{}] 成功, 建议将：{}设置为加速站\r\n".format(
                                                get.image, registry_list[0])
                                        )
                                except:
                                    import traceback
                                    print(traceback.format_exc())
                                    pass
                        else:
                            get._ws.send("bt_failed, 拉取失败!{}\r\n".format(output['errorDetail']))

                        return

                    if 'status' in output:
                        output_str = output['status']
                        if output_str == "Downloading":
                            progress = output['progressDetail']
                            if not progress: continue
                            current_mb = progress['current'] / (1024 * 1024)  # 将当前字节数转换为兆字节
                            total_mb = progress['total'] / (1024 * 1024)  # 将总字节数转换为兆字节
                            progress_str = "Downloading: {:.2f}MB/{:.2f}MB, {}%".format(current_mb, total_mb, int(
                                progress['current'] * 100 / progress['total']))
                            if progress_str != last_progress_str:
                                get._ws.send(progress_str + "\r\n")
                                last_progress_str = progress_str
                        else:
                            if output_str != last_result:
                                get._ws.send(output_str + "\r\n")
                                last_result = output_str
                    time.sleep(0.1)
                except StopIteration:
                    get._ws.send("bt_successful, 镜像拉取 [{}] 成功\r\n".format(get.image))
                    return public.returnMsg(True, "拉取镜像成功!")
                except ValueError:
                    get._ws.send("bt_failed, 拉取镜像失败!\r\n")
                    return public.returnMsg(False, "拉取镜像失败!")

        except docker.errors.ImageNotFound as e:
            if "pull access denied for" in str(e):
                get._ws.send("bt_failed, 拉取失败，镜像不存在，或该镜像可能是私有镜像，需要输入dockerhub的账号密码!\r\n")
                return
            get._ws.send("bt_failed, 拉取失败!{}\r\n".format(e))
            return

        except docker.errors.NotFound as e:
            if "not found: manifest unknown" in str(e):
                get._ws.send("bt_failed, 镜像拉取失败，仓库中没有这个镜像!\r\n")
                return
            get._ws.send("bt_failed, 拉取失败!{}\r\n".format(e))
            return

        except docker.errors.APIError as e:
            if "invalid tag format" in str(e):
                get._ws.send("bt_failed, 拉取失败, 镜像格式错误, 如: nginx:v 1!\r\n")
                return
            get._ws.send("bt_failed, 拉取失败!{}\r\n".format(e))
            return

    # 拉取镜像
    def pull_high_api(self, get):
        """
        :param image
        :param url
        :param registry
        :param username 拉取私有镜像时填写
        :param password 拉取私有镜像时填写
        :param get:
        :return:
        """
        import docker.errors
        try:
            if ':' not in get.image:
                get.image = '{}:latest'.format(get.image)
            auth_data = {
                "username": get.username,
                "password": get.password,
                "registry": get.registry if get.registry else None
            }

            auth_conf = auth_data if get.username else None

            if get.registry != "docker.io":
                get.image = "{}/{}/{}".format(get.registry, get.namespace, get.image)

            ret = self.docker_client(get.url).images.pull(repository=get.image, auth_config=auth_conf)
            if ret:
                return public.returnMsg(True, '拉取镜像成功.')
            else:
                return public.returnMsg(False, '可能没有这个镜像.')

        except docker.errors.ImageNotFound as e:
            if "pull access denied for" in str(e):
                return public.returnMsg(False, "拉取镜像失败, 这个是私有镜像，请输入账号密码!")
            return public.returnMsg(False, "拉取镜像失败  原因: {}".format(e))

    def image_for_host(self, get):
        """
        获取镜像大小和获取镜像数量
        :param get:
        :return:
        """
        res = self.image_list(get)
        if not res['status']: return res

        num = len(res['msg']['images_list'])
        size = 0

        for i in res['msg']['images_list']:
            size += i['size']
        return public.returnMsg(True, {'num': num, 'size': size})

    def prune(self, get):
        """
        删除无用的镜像
        :param get:
        :return:
        """
        dang_ling = True if "filters" in get and get.filters == "0" else False

        try:
            res = self.docker_client(self._url).images.prune(filters={'dangling': dang_ling})

            if not res['ImagesDeleted']:
                return public.returnMsg(True, "没有无用镜像!")

            dp.write_log("删除无用镜像成功!")
            return public.returnMsg(True, "删除成功!")

        except docker.errors.APIError as e:
            return public.returnMsg(False, "删除失败!{}".format(e))
        except Exception as e:
            if str(e).find("Read timed out") != -1:
                return "删除无用镜像失败,连接docker超时,请尝试重启docker服务后再试！"
            return public.returnMsg(False, "删除失败!{}".format(e))

    # 2024/5/17 下午6:30 构造返回结果
    def structure_result(self, results, sk_images_list):
        '''
            @name
            @author wzz <2024/5/17 下午6:30>
            @param "data":{"参数名":""} <数据类型> 参数描述
            @return dict{"status":True/False,"msg":"提示信息"}
        '''
        for r in results:
            r["is_pull"] = 0
            r['id'] = ""
            for image in sk_images_list:
                if image is None: continue
                i_RepoTags = image['RepoTags'][0] if not image['RepoTags'] is None and len(
                    image['RepoTags']) != 0 else "<none>"
                if i_RepoTags == "<none>": continue
                if r['name'] in i_RepoTags and i_RepoTags == "{}:latest".format(r['name']):
                    r["is_pull"] = 1
                    r['id'] = image['Id']

        return sorted(results, key=lambda x: x['star_count'], reverse=True)

    # 2023/12/13 上午 11:08 镜像搜索
    def search(self, get):
        '''
            @name 镜像搜索，docker hub官方镜像列表
                从docker hub官方镜像列表获取最新排序镜像
                数据库在/www/server/panel/class/btdockerModel/config/docker_hub_repos.db
                每隔1个月从官网同步一次
                脚本在/www/server/panel/class/btdockerModel/script/syncreposdb.py
            @author wzz <2023/12/13 下午 3:41>
            @param 参数名<数据类型> 参数描述
            @return 数据类型
        '''
        try:
            get.name = get.get("name/s", "")
            keywords_to_exclude = ["开心版", "习近平", "xijinping", "xijinping615"]
            if get.name in keywords_to_exclude: return []

            if get.name == "":
                from btdockerModel.dockerSock import image
                sk_image = image.dockerImage()
                sk_images_list = sk_image.get_images()
                # 2024/3/20 上午 10:10 如果get.name是空，则返回docker_hub_repos.db中results表的所有镜像
                import db, os
                sql = db.Sql()
                sql.dbfile('{}/class/btdockerModel/config/docker_hub_repos.db'.format(public.get_panel_path()))
                # 2024/3/20 上午 10:24 按照star_count排序
                results = sql.table('results').field('name,description,star_count,is_official').order('star_count desc').select()
                if not results: return []

                return self.structure_result(results, sk_images_list)

            import requests
            url = "https://docker.1ms.run/v1/search"
            query = {
                "q": public.xssencode2(get.name),
                "n": 25,
                "page": 1
            }
            search_result = requests.get(url, params=query, timeout=5).json()
            if not search_result: return []

            filtered_results = [
                item for item in search_result["results"]
                if not any(keyword in item.get("description", "").lower() for keyword in keywords_to_exclude)
            ]

            return sorted(filtered_results, key=lambda x: x['star_count'], reverse=True)
        except Exception as e:
            # if os.path.exists('data/debug.pl'):
            #     print(public.get_error_info())
            # public.print_log(public.get_error_info())
            return []
    # 拉取容器日志
    def get_cmd_log(self, get):
        """
        拉取容器日志
        @param get:
        @return:
        """
        get.wsLogTitle = "开始执行命令,请等待..."
        get._log_path = self._rCmd_log
        return self.get_ws_log(get)