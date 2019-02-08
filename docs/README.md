# Threefold grid broker

During the fist beta phase of the public launch of the TF grid, beta tester will be able to reserve 2 kind of workload on the grid.

- Zero-OS virtual machines
- S3 archive storage instances

**At the time of writing, everything happens on the testnet network**
**Don't send real TFT from the main network !!**

## How to make a reservation

The reservation is done by sending some TFT to the specific address with some metadata attached to the transaction.

Example how to reserve a virtual Zero-OS:
1. make sure you have a wallet on the testnet network
2. create a file `data.json` that will contains the decription of what you want to reserve
```json
{"type":"vm", "size":1, "email": "user1@mailinator.com"}
```
3. send some money to `019bc85e0d710d928f163cbe9bf9f4911462488468ab66b758e178ea7ef978992fc203130127b7` and attachd the content of `data.json` into the transaction

    if needed, unlock you wallet
    ```
    tfchainc wallet unlock
    ```
    send the TFTs
    ```
    tfchainc wallet send coins --data "$(cat data.json)" 019bc85e0d710d928f163cbe9bf9f4911462488468ab66b758e178ea7ef978992fc203130127b7 1
    ```

### Amount of TFT for each type of reservation:
|type|size|amount| CPU | Memory | Storage   |
| -- | --| --    | --  | --     | --     |
| vm | 1 | 1     | 1   | 2GiB   | 10 GiB |
| vm | 2 | 4     | 2   | 4GiB   | 40 GiB |
| s3 | 1 | 10    |     |        | 50 GiB |
| s3 | 2 | 40    |     |        | 100 GiB|

## How to get TFT on the testnet network

If you don't have any TFT in your testnet wallet, you can use http://faucet.testnet.threefoldtoken.com/.
Using this faucet, you can be granted with 300 TFT on any testnet address