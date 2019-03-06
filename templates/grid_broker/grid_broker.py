from jumpscale import j
from zerorobot.template.base import TemplateBase
from zerorobot.service_collection import ServiceConflictError
from nacl.signing import VerifyKey

import time
import requests

RESERVATION_UID = 'github.com/threefoldtech/grid_broker/reservation/0.0.1'
# Test notary
NOTARY_URL = 'http://10.241.78.116:6830'


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
                data = self._parse_tx_data(tx)
                # refund if there is not data
                if not data:
                    self._refund(tx)
            except Exception as err:
                # malformed data, refund transaction, though we can't notify the person that this happened
                self.logger.info("error parsing transaction data of tx %s: %s", tx.id, str(err))
                self._refund(tx)
                self.data['processed'][tx.id] = True
                continue

            # try to deploy the reservation
            try:
                connection_info = self._deploy(tx, data)
                self.logger.info("transaction processed %s", tx.id)
                # insert connection info into mail
                if connection_info:
                    self._send_connection_info(data['email'], connection_info)
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
            task = s.schedule_action('install').wait(die=True)
            return task.result
        except ServiceConflictError:
            # skip the creation of the service since it already exists
            pass
        finally:
            self.save()

    def _refund(self, tx):
        if not tx.amount > DEFAULT_MINERFEE:
            self.logger.info("not refunding tx %s, amount too low", tx.id)
        self.logger.info("refunding tx %s to %s", tx.id, tx.from_addresses[0])
        self._wallet.send_money((tx.amount - DEFAULT_MINERFEE)/TFT_PRECISION, tx.from_addresses[0])

    def _send_connection_info(self, email, data):
        if data[0] == 'vm':
            self._notify_user(
                email,
                "Your virtual 0-OS is ready on the Threefold grid",
                _vm_template.format(robot_url=data[1], zos_addr=data[2], vnc_addr=data[3])
            )
        elif data[0] == 's3':
            self._notify_user(
                email,
                "Your S3 archive server is ready on the Threefold grid",
                _s3_template.format(urls=data[1], login=data[2], password=data[3], domain=data[4])
            )
        else:
            self.logger.error("Can't send connection info for %s", data[0])

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

    def _parse_tx_data(self, tx):
        """
        transaction data is a hash
        expected notary format:
            content: encrypted content
            signature: hex encoded signature
            3bot id: id of the 3bot
        """
        data_key = tx.data
        if not data_key:
            return
        key = data_key.decode('utf-8')

        data = self._get_data(key)
        if not data:
            return

        # verify signature
        verification_key = self._get_3bot_key(data['threebot_id'])
        if not self._verify_signature(verification_key, data['content'], data['content_signature']):
            return

        # decrypt data
        signing_key = self._wallet.private_key(tx.to_address)
        if not signing_key:
            return

        decrypted_data = self._decrypt_data(verification_key, signing_key, data['content'])
        data_dict = j.data.serializer.msgpack.loads(decrypted_data.decode('utf-8'))
        data_dict['txId'] = tx.id
        data_dict['amount'] = tx.amount
        return data_dict

    def _get_data(self, key):
        """
        get data from the notary associated with a key. The key is assumed to be in bytes form
        """
        # we should always be able to reach the notary so don't catch an error
        response = requests.get('{}/get?key={}'.format(NOTARY_URL, key, timeout=30))
        if response.status_code != 200:
            return None
        return response.json()

    def _verify_signature(self, verification_key, content, signature):
        """
        verify data
        returns content if verification is successful, None otherwise
        """
        try:
            return j.data.nacl.verify_ed25519(content, signature, verification_key)
        except:
            return None

    def _decrypt_data(self, verification_key, signing_key, content):
        """
        Decrypt data by converting a verfication key and signing key to their respective
        curve25519 public/private keys. verification and signing key are instances of
        nacl.signing.(VerifyKey|SigningKey). Content is assumed to be in byte form
        """
        private_key = j.data.nacl.signing_key_to_private_key(signing_key)
        public_key = j.data.nacl.verify_key_to_public_key(verification_key)
        decrypted_content = j.data.nacl.decrypt_curve25519(content, private_key, public_key)
        return decrypted_content

    def _get_3bot_key(self, id):
        """
        get the key from the 3bot with the given id
        """
        key = self._wallet.get_3bot_key(id)
        algo, key = key.split(':')
        if algo is not 'ed25519':
            return None
        keybytes = bytes.fromhex(key)
        return VerifyKey(keybytes)

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

_s3_template = """
<html>
<body>
    <h1>You S3 archive server has been deployed</h1>
    <div class="content">
        <p>Make sure you have joined the <a href="https://github.com/threefoldtech/home/blob/master/docs/threefold_grid/networks.md#public-threefold-network-9bee8941b5717835">public
                threefold zerotier network</a> : <em>9bee8941b5717835</em></p>
        <p>
            <ul>
                <li>S3 url: {urls}</li>
                <li>S3 domain: {domain}</li>
                <li>Login: {login}</li>
                <li>Password: {password}</li>
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
