import random
import time

from grid_broker import TransactionWatcher


class TransactionMock:

    def __init__(self, amount, data=b''):
        self.amount = amount
        self.data = data


class WalletMock:

    def __init__(self):
        self._transactions = []

    def list_incoming_transactions(self):
        for i in range(int(random.random() * 10)):
            tx = TransactionMock(random.random() * 100)
            self._transactions.append(tx)
        return self._transactions


def test_watcher():
    """
    test the logic of the streaming of 
    new transaction from the TransactionWatcher

    since the WalletMock generate up to 10 transaction everytime
    list_incoming_transactions, we assert the new transactions
    return by the watcher are never bigger then 10
    if that would be the case, our logic is wrong
    """

    wallet = WalletMock()
    watcher = TransactionWatcher(wallet)
    count = 0
    for _ in range(3):
        for tx in watcher.watch():
            count += 1
    assert count < 30
