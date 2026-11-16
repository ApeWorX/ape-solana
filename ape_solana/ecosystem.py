from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, cast

from ape.api.networks import EcosystemAPI
from ape.api.providers import BlockAPI
from ape.exceptions import APINotImplementedError, ConversionError
from ape.types.address import AddressType
from pydantic import Field

from ape_solana._converters import to_pubkey
from ape_solana.constants import ECOSYSTEM_NAME
from ape_solana.transactions import SolanaReceipt, SolanaTransaction

if TYPE_CHECKING:
    from ape.types.address import RawAddress
    from ape.types.events import ContractLog
    from eth_pydantic_types import HexBytes
    from ethpm_types.abi import ConstructorABI, EventABI, MethodABI
    from solders.pubkey import Pubkey


class SolanaBlock(BlockAPI):
    """
    A Solana block. ``number`` is the slot and ``hash`` is the base58 blockhash.
    """

    number: int = 0  # type: ignore[assignment]
    hash: str | None = None
    parent_hash: str | None = Field(default=None, alias="parentHash")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} slot={self.number} hash={self.hash}>"

    def __str__(self) -> str:
        return repr(self)


class Solana(EcosystemAPI):
    name: str = ECOSYSTEM_NAME
    fee_token_symbol: str = "SOL"
    fee_token_decimals: int = 9

    @classmethod
    def decode_address(cls, raw_address: "RawAddress | Pubkey") -> AddressType:
        if isinstance(raw_address, int):
            raise ConversionError("Solana addresses cannot be integers.")

        try:
            return cast(AddressType, str(to_pubkey(raw_address)))
        except ValueError as err:
            raise ConversionError(f"Invalid Solana address '{raw_address}'.") from err

    @classmethod
    def encode_address(cls, address: AddressType) -> "RawAddress":
        return str(address)

    def decode_receipt(self, data: dict) -> SolanaReceipt:
        return SolanaReceipt.model_validate(data)

    def decode_block(self, data: dict) -> SolanaBlock:
        return SolanaBlock.model_validate(data)

    def create_transaction(self, **kwargs) -> SolanaTransaction:
        return SolanaTransaction.model_validate(kwargs)

    def encode_deployment(
        self, deployment_bytecode: "HexBytes", abi: "ConstructorABI", *args, **kwargs
    ) -> SolanaTransaction:
        # TODO: Deploy programs through the upgradeable BPF loader.
        raise APINotImplementedError("Program deployment is not yet supported on Solana.")

    def encode_transaction(
        self, address: AddressType, abi: "MethodABI", *args, **kwargs
    ) -> SolanaTransaction:
        # TODO: Encode Anchor instructions from an IDL.
        raise APINotImplementedError("Encoding program calls is not yet supported on Solana.")

    def decode_logs(self, logs: Sequence[dict], *events: "EventABI") -> Iterator["ContractLog"]:
        # TODO: Decode Anchor events.
        raise APINotImplementedError("Event decoding is not yet supported on Solana.")

    def encode_calldata(self, abi: "ConstructorABI | MethodABI", *args: Any) -> "HexBytes":
        raise APINotImplementedError("Calldata encoding is not yet supported on Solana.")

    def decode_calldata(self, abi: "ConstructorABI | MethodABI", calldata: bytes) -> dict:
        raise APINotImplementedError("Calldata decoding is not yet supported on Solana.")

    def decode_returndata(self, abi: "MethodABI", raw_data: bytes) -> Any:
        raise APINotImplementedError("Return data decoding is not yet supported on Solana.")
