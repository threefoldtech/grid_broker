# Threefold grid broker

During the fist beta phase of the public launch of the TF grid, beta tester will be able to reserve 2 kind of workload on the grid.

- Zero-OS virtual machines
- S3 archive storage instances

**At the time of writing, everything happens on the testnet network**
**Don't send real TFT from the main network !!**
## How to reserve some capacity on the Threefold Grid

This document assumes you are familiar with Jumpscale and you already have
a jumpscale installation ready. If you don't head to https://github.com/threefoldtech/jumpscaleX/blob/development/docs/Installation/install.md

### summary
1. [Create a TFchain wallet](#Create-a-TFchain-wallet)
2. [Get some TFT from our faucet](Get-some-TFT-from-our-faucet)
3. [Register a ThreeBot](Register-a-ThreeBot)
4. [Do a reservation](Do-a-reservation)

#### 1. Create a TFchain wallet

In kosmos, create a TFChain client
```python
c = j.clients.tfchain.new('my_client', network_type='TEST')
```
The network_type is important, if you omit this, you will play with real TFT, so be careful

With your new client, create a TFChain wallet:
```python
w = c.wallets.my_wallet.new("my_wallet") # a new seed will be generated
```
or recover an existing wallet using its seed:
```python
w = c.wallets.my_wallet.new("my_wallet", seed="blast fortune level avoid luxury obey humble lawsuit hurry crowd life select express shuffle taxi foam soul denial glimpse task struggle youth hawk cram")
```

#### 2. Get some TFT from our faucet

Copy the address of your wallet
```python
w.address
0128b01507b17175f99fb4ca0fadf9115a3e85aae89b8dcdca9b610469281de9e849cf16c9afcdroot
```
Head to https://faucet.testnet.threefoldtoken.com/ and fill the from with your wallet address. Then check the balance on your wallet, after a couple of minutes you should see the 300TFT from the faucet.

```python
w.balance
wallet balance on height 223939 at 1029/03/04 11:05:22
300 TFT available 0 TFT locked
```

#### 3. Register a ThreeBot

Creating a new 3Bot record can be done as follows:

```python
result = w.threebot.record_new(
    months=1, # default is 1, can be omitted to keep it at default,
              # or can be anything of inclusive range of [1,24]
    names=["my3bot.example"], # names can be omitted as well, as long as you have 1 address
    addresses=["example.org"], # addresses can be omitted as well, as long as you have 1 name
    key_index=0) # optionally leave key_index at default value of None
result.transaction # transaction that was created, signed and if possible submitted
result.submitted   # True if submitted, False if not possible
                   # due to lack of signatures in MultiSig Coin Inputs
```

For mode detail about the 3Bot registration, go to the full documentation: https://github.com/threefoldtech/jumpscaleX/blob/development/Jumpscale/clients/blockchain/tfchain/README.md#create-and-manage-3bot-records

#### 4. Do a reservation

Example how to reserve a Zero-OS virtual machines:
```python
result = w.capacity.reserve_zos_vm(
    email='user@email.com', # the email on which you will received the connection information
    threebot_id='my3bot.example.org', # your threebot id, it can be any of the names you gave to your 3bot
    location='farm_name', # name of the farm or node id where to deploy the workload
    size=1) # each workload have a different size available
```

Example how to reserve a S3 archive storage:
```python
result = w.capacity.reserve_zos_vm(
    email='user@email.com', # the email on which you will received the connection information
    threebot_id='my3bot.example.org', # your threebot id, it can be any of the names you gave to your 3bot
    location='farm_name', # name of the farm where to deploy the workload
    size=1) # each workload have a different size available
```

The result of the reserve methods is a tuple containing the transaction and the submission status as a boolean.
You can check it on our [explorer](https://explorer.testnet.threefoldtoken.com/) by entering the transaction ID in the `Search by hash` field of the explorer form or using the tfchain client:

```python
transaction = c.transaction_get(result.transaction.id)
```

As soon as it is ready, usually within a few minutes, you will receive an email with the connection information.


### Amount of TFT for each type of reservation:
|type|size|amount| CPU | Memory | Storage   |
| -- | --| --    | --  | --     | --     |
| vm | 1 | 1     | 1   | 2GiB   | 10 GiB |
| vm | 2 | 4     | 2   | 4GiB   | 40 GiB |
| s3 | 1 | 10    |     |        | 50 GiB |
| s3 | 2 | 40    |     |        | 100 GiB|
