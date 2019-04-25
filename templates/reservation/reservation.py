import time

from requests.exceptions import HTTPError

from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.template.state import StateCheckError
from zerorobot.template.decorator import retry
from zerorobot.service_collection import ServiceNotFoundError

DAY = 86400
WEEK = 604800
DMVM_GUID = 'github.com/threefoldtech/0-templates/dm_vm/0.0.1'
S3_GUID = 'github.com/threefoldtech/0-templates/s3/0.0.1'
REVERSE_PROXY_UID = 'github.com/threefoldtech/0-templates/reverse_proxy/0.0.1'
NAMESPACE_GUID = 'github.com/threefoldtech/0-templates/namespace/0.0.1'

DIRECTORY_URL = 'https://capacity.threefoldtoken.com'


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
            'namespace': self._install_namespace,
            'reverse_proxy': self._install_proxy,
        }

        amount = price(self.data['type'], self.data['size'])
        if self.data['amount'] < amount:
            raise ValueError("transaction amount is to low to deploy the workload. given: %s needed: %s",
                             self.data['amount'], price)

        install = deploy_map.get(self.data['type'])
        if not install:
            raise ValueError("unsupported reservation type %s size %s" % (self.data['type'], self.data['size']))

        install_result = install(self.data['size'])
        self.state.set('actions', 'install', 'ok')
        return install_result

    def _install_vm(self, size):
        if size == 1:
            cpu = 1
            memory = 2048
            disk = 10
        elif size == 2:
            cpu = 2
            memory = 4096
            disk = 40
        else:
            raise ValueError('size can only be 1 or 2')

        # For the location we support both nodeID and farm name. Check if the location is known
        # as a farm name in the directory and if so, deploy on the least used node. else it is a
        # nodeID, so just try that for the deploy
        location = self.data['location']
        nodeID = get_least_used_node_from_farm_s3(location)
        if nodeID is not None:
            location = nodeID

        data = {
            'cpu': cpu,
            'disks': [{'diskType': 'ssd', 'label': 'cache', 'size': disk}],
            'image': 'zero-os:master',
            'kernelArgs': [{'key': 'development', 'name': 'developmet'}],
            'memory': memory,
            'mgmtNic': {'id': '9bee8941b5717835', 'type': 'zerotier', 'ztClient': 'tf_public'},
            'nodeId': location
        }
        vm = self.api.services.find_or_create(DMVM_GUID, self.data['txId'], data)
        vm.schedule_action('install').wait(die=True)
        vm.schedule_action('enable_vnc').wait(die=True)

        # save created service id
        # used to delete the service during cleanup
        self.data['createdServices'] = [{
            'robot': 'local',
            'id': vm.guid,
        }]

        return self._vm_connect_info()

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
        return {
            'type': 'vm',
            'robot_url': robot_url,
            'zos_addr': zos_addr,
            'vnc_addr': vnc_addr}

    def _install_s3(self, size):
        if size == 1:
            disk = 500
        elif size == 2:
            disk = 1000
        else:
            raise ValueError('size can only be 1 or 2')

        # for now only allow 'freefarm.s3-storage'
        if not self.data['location'] in ['freefarm.s3-storage']:
            raise ValueError('can only deploy s3 in freefarm.s3-storage')

        login = j.data.idgenerator.generateXCharID(8)
        password = j.data.idgenerator.generateXCharID(16)
        data = {
            'farmerIyoOrg': self.data['location'],
            'mgmtNic': {'id': '9bee8941b5717835', 'type': 'zerotier', 'ztClient': 'tf_public'},
            'storageType': 'hdd',
            'storageSize': disk,
            'minioLogin': login,
            'minioPassword': password,
            'nsName': j.data.idgenerator.generateGUID(),
            'dataShards': 4,
            'parityShards': 2,
        }
        s3 = self.api.services.find_or_create(S3_GUID, self.data['txId'], data)
        task = s3.schedule_action('install').wait(die=True)
        credentials = task.result

        task = s3.schedule_action('url')
        task.wait()
        if task.state != 'ok':
            self.logger.error("error retrieving S3 url: \n%s", task.eco.trace)
            return

        urls = task.result
        self.logger.info("s3 installed %s at", urls)

        rp_data = {
            'webGateway': self.data['webGateway'],
            'domain': '{}.wg01.grid.tf'.format(j.data.idgenerator.generateXCharID(6)),
            'servers': [urls['public']],
        }
        reverse_proxy = self.api.services.find_or_create(REVERSE_PROXY_UID, 'rp-%s' % s3.name, rp_data)
        reverse_proxy.schedule_action('install').wait(die=True)
        reverse_proxy.schedule_action('update_servers', args={'servers': [urls['public']]}).wait(die=True)

        # save created services id
        # used to delete the service during cleanup
        self.data['createdServices'] = [
            {
                'robot': 'local',
                'id': s3.guid,
            },
            {
                'robot': 'local',
                'id': reverse_proxy.guid,
            },
        ]

        connection_info = self._s3_connect_info()
        # credentails need to be returned from the task since they are currently
        # different from the ones given when the S3 is created
        # See https://github.com/threefoldtech/0-templates/issues/303
        return {
            'type': 's3',
            'urls': connection_info['url'],
            'login': credentials['login'],
            'password': credentials['password'],
            'domain': connection_info['domain']}

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

        rp = self.api.services.get(template_uid=REVERSE_PROXY_UID, name='rp-{}'.format(self.data['txId']))
        return {
            'type': 's3',
            'url': urls['public'],
            'login': s3.data['minioLogin_'],
            'password': s3.data['minioPassword_'],
            'domain': rp.data['domain']}

    def _install_namespace(self, size):
        # convert enum number to string
        #  see https://github.com/threefoldtech/jumpscaleX/blob/development/Jumpscale/clients/blockchain/tfchain/schemas/reservation_namespace.schema#L8
        disk_type_map = {
            1: 'hdd',
            2: 'ssd',
        }
        mode_map = {
            1: 'seq',
            2: 'user',
            3: 'direct',
        }
        self.data['diskType'] = disk_type_map[self.data['disk_type']]
        self.data['namespaceMode'] = mode_map[self.data['mode']]

        location = self.data['location']
        disk_type = self.data['diskType']
        node_detail = capacity_planning_namespace(location, disk_type)
        robot = self.api.robots.get(node_detail['node_id'], node_detail['robot_address'])

        password = self.data['password'] if self.data['password'] else j.data.idgenerator.generateXCharID(16)

        data = {
            'size': size,
            'diskType': disk_type,
            'mode': self.data['namespaceMode'],
            'public': False,
            'password': password,
            'nsName': j.data.idgenerator.generateGUID(),
        }
        ns = robot.services.find_or_create(NAMESPACE_GUID, self.data['txId'], data)
        ns.schedule_action('install').wait(die=True)
        task = ns.schedule_action('connection_info').wait(die=True)
        connection_info = task.result
        self.logger.info("namespace %s installed", ns.name)

        # save created service id
        # used to delete the service during cleanup
        self.data['createdServices'] = [{
            'robot': node_detail['node_id'],
            'id': ns.guid,
        }]

        return {
            'type': 'namespace',
            'ip': connection_info['ip'],
            'port': connection_info['port'],
            'password': data['password'],
            'nsName': data['nsName'],
        }

    def _install_proxy(self, *args, **kwargs):
        self.data['backendUrls'] = self.data.pop('backend_urls')
        servers = self.data['backendUrls']
        if not isinstance(servers, list):
            servers = [servers]

        data = {
            'webGateway': self.data['webGateway'],
            'domain': self.data['domain'],
            'servers': servers,
        }
        reverse_proxy = self.api.services.find_or_create(REVERSE_PROXY_UID, self.data['txId'], data)
        reverse_proxy.schedule_action('install').wait(die=True)

        # save created service id
        # used to delete the service during cleanup
        self.data['createdServices'] = [{
            'robot': 'local',
            'id': reverse_proxy.guid,
        }]

        wg = self.api.services.get(name=self.data['webGateway'])
        return {
            'type': 'reverse_proxy',
            'domain': data['domain'],
            'backends': data['servers'],
            'ip': wg.data['publicIps'][0],  # for now only one, we might support multiple IP in the future
        }

    def _cleanup(self):
        try:
            self.state.check('actions', 'cleanup', 'ok')
        except StateCheckError:
            created = self.data['creationTimestamp']

            if (time.time() - created) > WEEK:
                self.logger.info("reservation has expired, uninstalling")
                for created_service in self.data.get('createdServices', []):
                    self._cleanup_service(created_service['robot'], created_service['id'])
                self.state.set('actions', 'cleanup', 'ok')

    def _cleanup_service(self, robot, service_id):
        if robot == 'local':
            api = self.api
        else:
            api = self.api.robots.get(robot)

        try:
            service = api.services.guids(service_id)
            self.logger.info("uninstalling {template_name} - {name}".format(
                name=service.name,
                template_name=service.template_uid.name))
            service.schedule_action('uninstall').wait(die=True)
            service.delete()
        except ServiceNotFoundError:
            pass


def _get_farm_nodes(farmname):
    """
    get a list of online nodes in the given farm
    """
    return list(j.sal_zos.farm.get(farmname).filter_online_nodes())


def get_least_used_node_from_farm_s3(farmname):
    """
    get the node ID of the least used node in a given farm based on cru/mru/sru
    """
    nodes = _get_farm_nodes(farmname)
    if not nodes:
        return

    def key(node):
        return (-node['total_resources']['cru'],
                -node['total_resources']['mru'],
                -node['total_resources']['sru'],
                node['used_resources']['cru'],
                node['used_resources']['mru'],
                node['used_resources']['sru'])
    return sorted(nodes, key=key)[0]['node_id']


def capacity_planning_namespace(location, disk_type):
    """
    get the node detail of the node or farm pointed by location
    if location is a node id, return this node detail
    if location is a farm name, return the least used node detail
    """
    if disk_type == 'ssd':
        resource = 'sru'
    elif disk_type == 'hdd':
        resource = 'hru'
    else:
        raise ValueError("disk_type can only be 'ssd' or 'hdd'")

    # first check if location is a node id
    directory = j.clients.threefold_directory.get()
    try:
        _, resp = directory.api.GetCapacity(location)
        return resp.json()
    except HTTPError as err:
        if err.response.status_code != 404:
            raise err

    # if it's not a node id, try as a farm name
    nodes = _get_farm_nodes(location)
    if not nodes:
        raise ValueError("no nodes found in farm %s" % location)

    def key(node):
        return (-node['total_resources'][resource],
                node['used_resources'][resource])
    return sorted(nodes, key=key)[0]


def price(typ, size):
    if typ == 's3':
        return s3_price(size)
    elif typ == 'vm':
        return vm_price(size)
    elif typ == 'namespace':
        return namespace_price(size)
    elif typ == 'reverse_proxy':
        return proxy_price(size)
    else:
        raise ValueError("unsupported reservation type")


def s3_price(size):
    if size == 1:
        return 41650000000.0
    elif size == 2:
        return 83300000000.0
    else:
        raise ValueError("size for s3 can only be 1 or 2")


def vm_price(size):
    if size == 1:
        return 41650000000.0
    elif size == 2:
        return 83300000000.0
    else:
        raise ValueError("size for vm can only be 1 or 2")


def namespace_price(size):
    return size * 83300000000.0


def proxy_price(size):
    return 10000000000
