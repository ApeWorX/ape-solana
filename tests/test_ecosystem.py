import ape
import pytest
from ape.exceptions import ConversionError
from ape.types.address import AddressType


def test_convert_address(create_account):
    account = create_account(autosign=False)

    assert ape.convert(account.address, AddressType) == account.address
    assert ape.convert(account, AddressType) == account.address
    assert ape.convert(account.pubkey, AddressType) == account.address

    transaction = ape.networks.solana.create_transaction(sender=account, receiver=account.pubkey)
    assert transaction.sender == transaction.receiver == account.address

    with pytest.raises(ConversionError):
        ape.networks.solana.decode_address("not-a-solana-address")
