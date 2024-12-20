import sys, os
import time
os.chdir('/www/server/panel')
sys.path.insert(0, "class/")
sys.path.insert(0, '/www/server/panel')
import public
import PluginLoader

class main:

    def __check_auth(self):
        from pluginAuth import Plugin
        plugin_obj = Plugin(False)
        plugin_list = plugin_obj.get_plugin_list()
        return int(plugin_list['ltd']) > time.time()

    def run(self):
        pay = self.__check_auth()
        if not pay:
            from panelSite import panelSite
            site_obj = panelSite()
            res = site_obj.get_Scan(None)
            if int(res['loophole_num']):
                msg = ['扫描网站【{}】，发现【{}】条漏洞'.format(res['site_num'], res['loophole_num'])]
                return msg
            else:
                return ['扫描网站【{}】个，状态【安全】'.format(res['site_num'])]
        else:
            args = public.dict_obj()
            args.model_index = 'project'
            res = PluginLoader.module_run('scanning', 'startScan', args)
            if int(res['loophole_num']):
                msg = ['扫描网站【{}】，发现【{}】条漏洞'.format(res['site_num'], res['loophole_num'])]
                for i in res['info']:
                    msg.append('网站【{}】，存在【{}】个风险项，请及时处理'.format(i['rname'] if i['rname'] else i['name'], len(i['cms'])))
                return msg
            else:
                return ['扫描网站【{}】个，状态【安全】'.format(res['site_num'])]


if __name__ == '__main__':
    channels = sys.argv[1]
    main = main()
    msg = main.run()
    data = public.get_push_info('网站漏洞扫描', msg)
    for channel in channels.split(','):
        try:
            obj = public.init_msg(channel)
            obj.send_msg(data['msg'])
            print('{}通道发送成功'.format(channel))
        except:
            print('{}通道发送失败'.format(channel))
