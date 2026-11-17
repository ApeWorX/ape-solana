import base64

import pytest
from ape.exceptions import TransactionError
from solders.system_program import TransferParams, transfer

from ape_solana.constants import LAMPORTS_PER_SIGNATURE
from ape_solana.provider import decode_rpc_transaction


def test_transfer_moves_lamports(provider, owner, receiver):
    owner_balance = owner.balance

    receipt = owner.transfer(str(receiver), 1_000_000)

    assert receipt.status == 1
    assert receipt.fee == LAMPORTS_PER_SIGNATURE
    assert provider.get_balance(str(receiver)) == 1_000_000
    assert owner.balance == owner_balance - 1_000_000 - receipt.fee
    assert provider.get_receipt(receipt.transaction.txn_hash.to_0x_hex()) == receipt
    assert owner.check_signature(receipt.transaction)


def test_transfer_identical_twice(provider, owner, receiver):
    owner.transfer(str(receiver), 1_000_000)
    owner.transfer(str(receiver), 1_000_000)

    assert provider.get_balance(str(receiver)) == 2_000_000


def test_call_failure_reports_program_logs(provider, owner, receiver):
    oversized_transfer = transfer(
        TransferParams(from_pubkey=owner.pubkey, to_pubkey=receiver, lamports=10**18)
    )
    with pytest.raises(TransactionError, match="insufficient lamports"):
        owner.call(provider.network.ecosystem.create_transaction(instructions=[oversized_transfer]))

    receipt = owner.call(
        provider.network.ecosystem.create_transaction(
            instructions=[oversized_transfer], raise_on_revert=False
        )
    )

    assert receipt.failed
    assert receipt.fee == LAMPORTS_PER_SIGNATURE


def test_get_block_by_blockhash(provider, owner, receiver):
    receipt = owner.transfer(str(receiver), 1_000_000)
    block = provider.get_block(receipt.block_number)

    assert provider.get_block(block.hash).number == receipt.block_number
    assert list(provider.get_transactions_by_block(block.hash)) == [receipt.transaction]


def test_decode_rpc_transaction_round_trip(provider, owner, receiver):
    receipt = owner.transfer(str(receiver), 1_000_000)
    encoded_transaction = base64.b64encode(receipt.transaction.serialize_transaction()).decode()

    decoded_transaction = decode_rpc_transaction(
        {"transaction": [encoded_transaction, "base64"], "version": "legacy"}
    )

    assert (
        decoded_transaction.serialize_transaction() == receipt.transaction.serialize_transaction()
    )
    assert decoded_transaction.transaction_id == receipt.txn_hash
