from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.service_collection import ServiceConflictError

RESERVATION_UID = 'github.com/threefoldtech/grid_broker/reservation/0.0.1'


class GridBroker(TemplateBase):

    version = '0.0.1'
    template_name = "grid_broker"

    def __init__(self, name, guid=None, data=None):
        super().__init__(name=name, guid=guid, data=data)
        self.recurring_action(self._watch_transactions, 60)
        self._wallet_ = None
        self._watcher_ = None

    @property
    def _wallet(self):
        if self._wallet_ is None:
            self._wallet_ = j.clients.tfchain.get(self.data['wallet']).wallet
        return self._wallet_

    @property
    def _watcher(self):
        if self._watcher_ is None:
            self._watcher_ = TransactionWatcher(self._wallet)
        return self._watcher_

    def _watch_transactions(self):
        if 'processed' not in self.data:
            self.data['processed'] = {}
        self.logger.info("look for new incoming transactions")
        for tx in self._watcher.watch():
            if self.data['processed'].get(tx.id, False):
                self.logger.info("tx %s already processed", tx.id)
                continue
            # try to parse the transaction data
            try:
                data = _parse_tx_data(tx)
            except Exception as err:
                # malformed data, refund transaction, though we can't notify the person that this happened
                self.logger.info("error parsing transaction data of tx %s: %s", tx.id, str(err))
                self._refund(tx)
                self.data['processed'][tx.id] = True
                return

            # try to deploy the reservation
            try:
                self._deploy(tx, data)
                self.logger.info("transaction processed %s", tx.id)
                # get connection info and insert into mail
                reservation = self.api.services.get(name=tx.id, template_uid=RESERVATION_UID)
                task = reservation.schedule_action('connection_info').wait(die=True)
                if task.state != 'ok':
                    raise Exception("can't get connection info")
                robot_url, zos_addr, vnc_addr = task.result
                self._notify_user(
                    data['email'],
                    "Your virtual 0-OS is ready on the Threefold grid",
                    _vm_template.format(robot_url=robot_url, zos_addr=zos_addr, vnc_addr=vnc_addr),
                )
            except Exception as err:
                self.logger.error("error processing transation %s: %s", tx.id, str(err))
                self._refund(tx)
                self._notify_user(
                    data['email'],
                    "Reservation failed",
                    _refund_template.format(address=tx.from_addresses[0])
                )
            finally:
                # even if a deploy errors, we refund so it is considered processed
                self.data['processed'][tx.id] = True

    def _deploy(self, tx, data):
        self.logger.info(
            "start processing transaction %s - %s", tx.id, tx.data)

        try:
            s = self.api.services.create(RESERVATION_UID, tx.id, data)
            s.schedule_action('install')
        except ServiceConflictError:
            # skip the creation of the service since it already exists
            pass

        self.save()

    def _refund(self, tx):
        if not tx.amount > DEFAULT_MINERFEE:
            self.logger.info("not refunding tx %s, amount too low", tx.id)
        self.logger.info("refunding tx %s to %s", tx.id, tx.from_addresses[0])
        self._wallet.send_money((tx.amount - DEFAULT_MINERFEE)/TFT_PRECISION, tx.from_addresses[0])

    def _notify_user(self, receiver, subject, content):
        clients = self.api.services.find(template_name='sendgrid_client')
        if not clients:
            self.logger.warning("there is no sendgrid client configured on the robot. cannot send email")
            return

        client = clients[0]
        client.schedule_action('send', {
            'sender': 'broker@grid.tf',
            'receiver': receiver,
            'subject': subject,
            'content': content,
        })


def _parse_tx_data(tx):
    """
    format:
    1 byte: type
    1 byte: size
    1 byte: len(location)
    len(location): location (nodeID for vm, farm name for s3)
    1 byte: len(email)
    len(email): email address
    """
    data = tx.data
    decoded_data = {}

    if data[0] == 1:
        decoded_data['type'] = 'vm'
    elif data[0] == 2:
        decoded_data['type'] = 's3'
    else:
        decoded_data['type'] = '???'

    decoded_data['size'] = data[1] 

    location_len = data[2]
    location = data[3:3+location_len].decode()
    decoded_data['location'] = location

    email_len = data[3+location_len]
    email = data[3+location_len+1:3+location_len+1+email_len].decode()
    decoded_data['email'] = email
 
    decoded_data['txId'] = tx.id
    decoded_data['amount'] = tx.amount
    return decoded_data


class TransactionWatcher:

    def __init__(self, wallet):
        self._wallet = wallet
        self.last_sent = 0

    def watch(self):
        txns = self._wallet.list_incoming_transactions()
        txns.reverse()
        try:
            for tx in txns[self.last_sent:]:
                self.last_sent += 1
                if self._is_locked(tx):
                    continue
                yield tx
        except IndexError:
            return

    def _is_locked(self, tx):
        return tx._locked

DEFAULT_MINERFEE = 100000000
TFT_PRECISION = 1000000000

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

_refund_template = """
<html>

<body>
    <h1>We could not complete your reservation at this time</h1>
    <div class="content">
        <p>Unfortunately, we could not complete your reservation. We will refund your reservation to {address}. Please try again at a later time</p>
    </div>
</body>
</html>
"""
