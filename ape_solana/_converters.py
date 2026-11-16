from typing import Any, cast

from ape.api.convert import ConverterAPI
from ape.types.address import AddressType
from solders.pubkey import Pubkey


def is_solana_address(value: Any) -> bool:
    if isinstance(value, Pubkey):
        return True

    if not isinstance(value, str) or value.startswith("0x"):
        return False

    try:
        Pubkey.from_string(value)
    except ValueError:
        return False

    return True


def to_pubkey(address: Any) -> Pubkey:
    if isinstance(address, Pubkey):
        return address

    if isinstance(address, (bytes, bytearray)):
        return Pubkey.from_bytes(bytes(address))

    if hasattr(address, "address"):
        return Pubkey.from_string(address.address)

    return Pubkey.from_string(address)


class SolanaAddressConverter(ConverterAPI):
    """
    Converts a base58 Solana public key, or a ``solders`` ``Pubkey``, to ``AddressType``.
    """

    def is_convertible(self, value: Any) -> bool:
        return is_solana_address(value)

    def convert(self, value: Any) -> AddressType:
        return cast(AddressType, str(to_pubkey(value)))
