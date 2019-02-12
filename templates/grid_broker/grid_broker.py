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
            try:
                self._deploy(tx)
                self.data['processed'][tx.id] = True
                self.logger.info("transaction processed %s", tx.id)
            except Exception as err:
                self.data['processed'][tx.id] = False
                self.logger.error("error processing transation %s: %s", tx.id, str(err))

    def _deploy(self, tx):
        self.logger.info(
            "start processing transaction %s - %s", tx.id, tx.data)

        data = _parse_tx_data(tx)
        try:
            s = self.api.services.create(RESERVATION_UID, tx.id, data)
            s.schedule_action('install')
        except ServiceConflictError:
            # skip the creation of the service since it already exists
            pass

        self.save()


def _parse_tx_data(tx):
    """
    format:
    {"type":"vm", "size":1,"email":"user@mail.com"}
    """
    data = tx.data
    if isinstance(data, bytes):
        data = data.decode()
    data = j.data.serializer.json.loads(data)
    data['txId'] = tx.id
    data['amount'] = tx.amount
    return data


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
