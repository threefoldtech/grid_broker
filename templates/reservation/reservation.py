import time

from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.service_collection import ServiceNotFoundError

WEEK = 604800


class Reservation(TemplateBase):

    version = '0.0.1'
    template_name = "reservation"

    def __init__(self, name, guid=None, data=None):
        super().__init__(name=name, guid=guid, data=data)
        self.recurring_action(self._cleanup, 3600*12)  # 12h

    def validate(self):
        if not self.data.get('creationTimestamp'):
            self.data['creationTimestamp'] = time.time()

    def install(self):
        deploy_map = {
            'vm': self._install_vm,
        }
        install = deploy_map.get(self.data['type'])
        if not install:
            raise ValueError("unsupported reservation type % s", self.data['type'])
        install()
        self.state.set('actions', 'install', 'ok')

    def _install_vm(self):
        data = {
            'cpu': 1,
            'disks': [{'diskType': 'hdd', 'label': 'cache', 'size': 10}],
            'ports': [
                {'name': 'robot', 'source': None, 'target': 6600},
                {'name': 'zos', 'source': None, 'target': 6379},
            ],
            'image': 'zero-os:master',
            'kernelArgs': [{'key': 'development', 'name': 'developmet'}],
            'memory': 2048,
            'mgmtNic': {'id': '8850338390ef9f69', 'type': 'zerotier'},
            'nodeId': 'ac1f6b4573d4'
        }
        vm = self.api.services.create('dm_vm', self.data['txId'], data)
        task = vm.schedule_action('install')
        task.wait(die=True)
        self.logger.info("vm installed %s", vm.schedule_action('info').wait(die=True).result)

    def _cleanup(self):
        type_map = {
            'vm': 'dm_vm',
        }
        created = self.data['creationTimestamp']

        if (time.time() - created) > WEEK:
            self.logger.info("reservation has expired, uninstalling")
            try:
                template_name = type_map.get(self.data['type'])
                service = self.api.services.get(name=self.data['txId'], template_name=template_name)
                service.schedule_action('uninstall').wait(die=True)
                service.delete()
            except ServiceNotFoundError:
                pass
            self.state.set('actions', 'cleanup', 'ok')
