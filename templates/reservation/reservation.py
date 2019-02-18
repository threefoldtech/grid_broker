import time

from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.template.decorator import retry
from zerorobot.service_collection import ServiceNotFoundError

DAY = 86400
WEEK = 604800
DMVM_GUID = 'github.com/threefoldtech/0-templates/dm_vm/0.0.1'
S3_GUID = 'github.com/threefoldtech/0-templates/s3/0.0.1'
REVERSE_PROXY_UID = 'github.com/threefoldtech/0-templates/reverse_proxy/0.0.1'

PRICE_MAP = {
    'vm': {
        1: 1000000000,
        2: 4000000000,
    },
    's3': {
        1: 10000000000,
        2: 40000000000,
    }
}


class Reservation(TemplateBase):

    version = '0.0.1'
    template_name = "reservation"

    def __init__(self, name, guid=None, data=None):
        super().__init__(name=name, guid=guid, data=data)
        self.recurring_action(self._cleanup, 3600*12)  # 12h

    def validate(self):
        if not self.data.get('creationTimestamp'):
            self.data['creationTimestamp'] = time.time()

    @retry((Exception), tries=4, delay=5, backoff=2, logger=None)
    def install(self):
        deploy_map = {
            'vm': self._install_vm,
            's3': self._install_s3,
        }

        price = PRICE_MAP.get(self.data['type'], {}).get(self.data['size'])
        if not price:
            raise ValueError("unsupported reservation type %s size %s", self.data['type'], self.data['size'])

        if self.data['amount'] < price:
            raise ValueError("transaction amount is to low to deploy the workload. given: %s needed: %s",
                             self.data['amount'], price)

        install = deploy_map.get(self.data['type'])
        if not install:
            raise ValueError("unsupported reservation type %s size %s" % (self.data['type'], self.data['size']))

        install(self.data['size'])
        self.state.set('actions', 'install', 'ok')

    def connection_info(self):
        if self.data['type'] == 'vm':
            return self._vm_connect_info()
        elif self.data['type'] == 's3':
            return self._s3_connect_info()

    def _install_vm(self, size):
        if size == 1:
            cpu = 1
            memory = 2048
            disk = 20
        elif size == 2:
            cpu = 2
            memory = 4096
            disk = 60
        else:
            raise ValueError('size can only be 1 or 2')

        data = {
            'cpu': cpu,
            'disks': [{'diskType': 'hdd', 'label': 'cache', 'size': disk}],
            'image': 'zero-os:master',
            'kernelArgs': [{'key': 'development', 'name': 'developmet'}],
            'memory': memory,
            'mgmtNic': {'id': '9bee8941b5717835', 'type': 'zerotier', 'ztClient': 'tf_public'},
            'nodeId': self.data['location']
            # 'nodeId': 'ac1f6b272370'
        }
        vm = self.api.services.find_or_create(DMVM_GUID, self.data['txId'], data)
        vm.schedule_action('install').wait(die=True)
        vm.schedule_action('enable_vnc').wait(die=True)

    def _install_s3(self, size):
        if size == 1:
            disk = 50
        elif size == 2:
            disk = 100
        else:
            raise ValueError('size can only be 1 or 2')

        # for now only allow 'kristof-farm-s3'
        if not self.data['location'] in ['kristof-farm-s3']:
            raise ValueError('can only deploy s3 in kristof-farm-s3')

        data = {
            'farmerIyoOrg': self.data['location'],
            'mgmtNic': {'id': '9bee8941b5717835', 'type': 'zerotier', 'ztClient': 'tf_public'},
            'storageType': 'hdd',
            'storageSize': disk,
            'minioLogin': j.data.idgenerator.generateXCharID(8),
            'minioPassword': j.data.idgenerator.generateXCharID(16),
            'nsName': j.data.idgenerator.generateGUID(),
        }
        s3 = self.api.services.find_or_create(S3_GUID, self.data['txId'], data)
        s3.schedule_action('install').wait(die=True)

        task = s3.schedule_action('url')
        task.wait()
        if task.state != 'ok':
            self.logger.error("error retrieving S3 url: \n%s", task.eco.trace)
            return

        urls = task.result
        self.logger.info("s3 installed %s at", urls)

        rp_data = {
            'webGateway': 'web_gateway',
            'domain': '',  # TODO: generate random domain ?
            'servers': [urls['public']],
        }
        reverse_proxy = self.api.services.find_or_create(template_uid=REVERSE_PROXY_UID, name='rp-%s' % s3.name)
        reverse_proxy.schedule_action('update_servers', args={'servers': [urls['public']]})

    def _vm_connect_info(self):
        vm = self.api.services.get(template_uid=DMVM_GUID, name=self.data['txId'])
        if vm is None:
            self.logger.error("Didn't find vm")
            return

        task = vm.schedule_action('info')
        task.wait()
        if task.state != 'ok':
            self.logger.error("error retrieving vm connection info: \n%s", task.eco.trace)
            return

        info = task.result

        vm_ip = info['zerotier']['ip']
        host_ip = info['host']['public_addr']
        robot_url = 'http://%s:6600' % vm_ip
        zos_addr = "%s:6379" % vm_ip
        vnc_addr = "%s:%s" % (host_ip, info['vnc'])
        return ('vm', robot_url, zos_addr, vnc_addr)

    def _s3_connect_info(self):
        s3 = self.api.services.get(template_uid=S3_GUID, name=self.data['txId'])
        if s3 is None:
            self.logger.error("Didn't find s3 instance")
            return

        task = s3.schedule_action('url')
        task.wait()
        if task.state != 'ok':
            self.logger.error("error retrieving s3 connection info: \n%s", task.eco.trace)
            return
        urls = task.result

        return ('s3', urls['public'], s3.data['minioLogin'], s3.data['minioPassword'])

    def _cleanup(self):
        created = self.data['creationTimestamp']
        now = int(time.time())

        if (time.time() - created) > WEEK:
            self.logger.info("reservation has expired, uninstalling")
            tids = self._get_template_ids()
            for tid in tids:
                self._cleanup_service(tid[0], tid[1])
            self.state.set('actions', 'cleanup', 'ok')

    def _get_template_ids(self):
        if self.data['type'] == 'vm':
            return [(self.data['txId'], 'dm_vm')]
        elif self.data['type'] == 's3':
            s3 = self.api.services.get(name=self.data['txId'], template_name='s3')
            return [('rp-%s' % s3.name, 'reverse_proxy'), (self.data['txId'], 's3')]
        else:
            self.logger.error("Can't uninstall service type %s", self.data['type'])

    def _cleanup_service(self, name, template_name):
        self.logger.info("uninstalling {template_name} - {name}".format(name=name, template_name=template_name))
        try:
            service = self.api.services.get(name=name, template_name=template_name)
            service.schedule_action('uninstall').wait(die=True)
            service.delete()
        except ServiceNotFoundError:
            pass

