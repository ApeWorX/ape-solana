import pytest
from solders.hash import Hash
from solders.message import MessageV0
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction, VersionedTransaction

from ape_solana.accounts import InvalidPasswordError, import_account_from_mnemonic, load_keypair


@pytest.mark.parametrize(
    "encoding", ["json-array", "base58", "hex-seed", "hex-keypair"], ids=lambda value: value
)
def test_load_keypair_formats(keypair, keypair_encodings, encoding):
    assert load_keypair(keypair_encodings[encoding]).pubkey() == keypair.pubkey()


def test_import_account_from_mnemonic_matches_phantom(passphrase):
    mnemonic = " ".join(["abandon"] * 11 + ["about"])
    account = import_account_from_mnemonic("phantom", passphrase, mnemonic)

    assert account.address == "HAgk14JpMQLgt6rVgv7cBQFJWFto5Dqxi472uT3DKpqk"
    assert account.decrypt_keypair(passphrase).pubkey() == account.pubkey
    with pytest.raises(InvalidPasswordError):
        account.decrypt_keypair("wrong-passphrase")

    account.keyfile_path.unlink()


def test_sign_message_round_trip(create_account):
    account = create_account()
    signature = account.sign_message("hello solana")

    assert account.check_signature("hello solana", signature)
    assert account.check_signature(b"hello solana", signature.to_solders())
    assert not account.check_signature("hello ethereum", signature)


def build_legacy_transaction(payer, instruction) -> Transaction:
    return Transaction.new_with_payer([instruction], payer)


def build_v0_transaction(payer, instruction) -> VersionedTransaction:
    message = MessageV0.try_compile(payer, [instruction], [], Hash.default())
    return VersionedTransaction.populate(message, [Signature.default()])


@pytest.mark.parametrize(
    "build_transaction",
    [
        pytest.param(build_legacy_transaction, id="legacy"),
        pytest.param(build_v0_transaction, id="v0"),
    ],
)
def test_sign_transaction_solders_types(create_account, receiver, build_transaction):
    account = create_account()
    instruction = transfer(
        TransferParams(from_pubkey=account.pubkey, to_pubkey=receiver, lamports=1)
    )
    unsigned_transaction = build_transaction(account.pubkey, instruction)

    signed_transaction = account.sign_transaction(unsigned_transaction)

    assert account.check_signature(signed_transaction)
    assert not account.check_signature(unsigned_transaction)
