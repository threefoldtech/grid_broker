import time

from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.service_collection import ServiceNotFoundError

DAY = 86400
WEEK = 604800
DMVM_GUID = 'github.com/threefoldtech/0-templates/dm_vm/0.0.1'

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

    def install(self):
        deploy_map = {
            'vm': self._install_vm,
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
            'nodeId': 'ac1f6b272370'  # TODO: capacity planning for node selection
            # 'nodeId': 'ac1f6b4573d4'
        }
        vm = self.api.services.find_or_create(DMVM_GUID, self.data['txId'], data)
        vm.schedule_action('install').wait(die=True)
        vm.schedule_action('enable_vnc')

        task = vm.schedule_action('info')
        task.wait()
        if task.state != 'ok':
            self.logger.error("error retrieving vm connection info: \n%s", task.eco.trace)
            return

        info = task.result
        self.logger.info("vm installed %s", info)

        vm_ip = info['zerotier']['ip']
        host_ip = info['host']['public_addr']
        robot_url = 'http://%s:6600' % vm_ip
        zos_addr = "%s:6379" % vm_ip
        vnc_addr = "%s:%s" % (host_ip, info['vnc'])

        self._notify_user(
            "Your virtual 0-OS is ready on the Threefold grid",
            _vm_template.format(robot_url=robot_url, zos_addr=zos_addr, vnc_addr=vnc_addr),
        )

    def _notify_user(self, subject, content):
        clients = self.api.services.find(template_name='sendgrid_client')
        if not clients:
            self.logger.warning("there is no sendgrid client configured on the robot. cannot send email")
            return

        client = clients[0]
        client.schedule_action('send', {
            'sender': 'broker@grid.tf',
            'receiver': self.data['email'],
            'subject': subject,
            'content': content,
        })

    def _cleanup(self):
        type_map = {
            'vm': 'dm_vm',
        }
        created = self.data['creationTimestamp']
        now = int(time.time())

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


_vm_template = """
<html>

<body>
    <h1>You virtual 0-OS has been deployed</h1>
    <div class="content">
        <p>Make sure you have joined the <a href="https://github.com/threefoldtech/home/blob/master/docs/threefold_grid/networks.md#public-threefold-network-9bee8941b5717835">public
                threefold zerotier network</a> : <em>9bee8941b5717835</em></p>
        <p>
            <ul>
                <li>0-OS address: {zos_addr}</li>
                <li>0-robot url: <a href="{robot_url}">{robot_url}</a></li>
                <li>VNC address: <pre>{vnc_addr}<pre></li>
            </ul>
        </p>
    </div>
</body>

</html>
"""
