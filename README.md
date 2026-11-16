# Quick Start

Ape ecosystem plugin for [Solana](https://solana.com).
It adds the `solana` ecosystem, its networks, providers, transactions, and keyfile-backed accounts.

## Dependencies

- [python3](https://www.python.org/downloads) version 3.10 up to 3.13.

## Installation

### via `ape`

```bash
ape plugins install solana
```

### via `pip`

```bash
pip install ape-solana
```

### via `setuptools`

```bash
git clone https://github.com/ApeWorX/ape-solana.git
cd ape-solana
python3 setup.py install
```

## Quick Usage

### Networks

| Network          | Default provider | Other providers                               |
| ---------------- | ---------------- | --------------------------------------------- |
| `solana:local`   | `litesvm`        | `solana` (`solana-test-validator` on `:8899`) |
| `solana:devnet`  | `solana`         |                                               |
| `solana:testnet` | `solana`         |                                               |
| `solana:mainnet` | `solana`         |                                               |

`litesvm` is an in-process Solana VM, so `solana:local` needs no validator.
The `solana` provider talks JSON-RPC and verifies the cluster's genesis hash on connect.

Set your own RPC in `ape-config.yaml`:

```yaml
solana:
  mainnet:
    uri: https://my-rpc.example.com
    commitment: finalized
```

### Accounts

Solana accounts live in encrypted keyfiles, the same format and UX as `ape accounts`:

```bash
ape solana accounts generate alice
ape solana accounts import bob                                     # base58, hex, or JSON array
ape solana accounts import carol --use-mnemonic                    # m/44'/501'/0'/0' by default
ape solana accounts import dave --keypair-file ~/.config/solana/id.json
ape solana accounts list
ape solana accounts export alice
ape solana airdrop --network solana:local --account alice --sol 5
```

Unlock non-interactively with the `APE_SOLANA_ACCOUNTS_<alias>_PASSPHRASE` environment variable.

### Transfers and transactions

```python
from ape import accounts, networks
from solders.system_program import TransferParams, transfer

alice = accounts.load("alice")
bob = accounts.load("bob")

with networks.solana.local.use_provider("litesvm"):
    alice.request_airdrop(10 * 10**9)
    receipt = alice.transfer(bob, 1_000_000)
    receipt.show_program_logs()

    instruction = transfer(
        TransferParams(from_pubkey=alice.pubkey, to_pubkey=bob.pubkey, lamports=1_000_000)
    )
    txn = networks.solana.create_transaction(instructions=[instruction])
    receipt = alice.call(txn)
```

Accounts also sign `solders` `Transaction` and `VersionedTransaction` objects directly:

```python
signed_transaction = alice.sign_transaction(unsigned_transaction)
assert alice.check_signature(signed_transaction)
```

### Messages

```python
signature = alice.sign_message("gm")
assert alice.check_signature("gm", signature)
print(signature)  # base58
```

## Not yet supported

- Program deployment and Anchor IDL-based program calls (`ContractInstance`, events).
- Read-only calls (`simulateTransaction`) and log queries.
- Building v0 transactions with address lookup tables (signing them already works).
- Test accounts and snapshots on `solana:local`.
- Launching `solana-test-validator` automatically.

## Development

This project is in development and should be considered an alpha.
Things might not be in their final state and breaking changes may occur.
Comments, questions, criticisms and pull requests are welcomed.
