import json
from typing import TYPE_CHECKING, Annotated

import click
from ape.api.transactions import ReceiptAPI, TransactionAPI
from ape.exceptions import APINotImplementedError, SignatureError, TransactionError
from eth_pydantic_types import HexBytes
from pydantic import ConfigDict, Field, PlainSerializer
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from ape_solana._converters import to_pubkey
from ape_solana.constants import LAMPORTS_PER_SOL

if TYPE_CHECKING:
    from ape.contracts.base import ContractEvent
    from ape.types.events import ContractLogContainer
    from ethpm_types.abi import EventABI
    from solders.pubkey import Pubkey


def serialize_instruction(instruction: Instruction) -> dict:
    return json.loads(instruction.to_json())


InstructionField = Annotated[
    Instruction, PlainSerializer(serialize_instruction, return_type=dict, when_used="json")
]


def is_writable_account(message: Message, account_index: int) -> bool:
    header = message.header
    num_signers = header.num_required_signatures
    if account_index < num_signers:
        return account_index < num_signers - header.num_readonly_signed_accounts

    return account_index < len(message.account_keys) - header.num_readonly_unsigned_accounts


def create_account_meta(message: Message, account_index: int) -> AccountMeta:
    return AccountMeta(
        pubkey=message.account_keys[account_index],
        is_signer=message.is_signer(account_index),
        is_writable=is_writable_account(message, account_index),
    )


def to_signature(value: str | bytes) -> Signature:
    if isinstance(value, bytes):
        return Signature.from_bytes(value)

    if value.startswith("0x"):
        return Signature.from_bytes(bytes.fromhex(value[2:]))

    return Signature.from_string(value)


class SolanaTransaction(TransactionAPI):
    """
    A legacy Solana transaction: the fee payer (``sender``), a list of instructions,
    and an optional native SOL transfer of ``value`` lamports to ``receiver``.
    """

    type: int = 0
    instructions: list[InstructionField] = Field(default_factory=list)
    recent_blockhash: str | None = None
    signatures: dict[str, str] = Field(default_factory=dict, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    @classmethod
    def from_solders(cls, transaction: Transaction, **kwargs) -> "SolanaTransaction":
        message = transaction.message
        account_keys = message.account_keys
        instructions = [
            Instruction(
                program_id=account_keys[compiled.program_id_index],
                data=bytes(compiled.data),
                accounts=[
                    create_account_meta(message, account_index)
                    for account_index in compiled.accounts
                ],
            )
            for compiled in message.instructions
        ]
        signer_keys = account_keys[: message.header.num_required_signatures]
        signatures = {
            str(signer): str(signature)
            for signer, signature in zip(signer_keys, transaction.signatures)
            if signature != Signature.default()
        }
        return cls(
            sender=str(account_keys[0]),
            instructions=instructions,
            recent_blockhash=str(message.recent_blockhash),
            signatures=signatures,
            **kwargs,
        )

    @property
    def fee_payer(self) -> "Pubkey":
        if not self.sender:
            raise TransactionError("Transaction missing `sender` (fee payer).")

        return to_pubkey(self.sender)

    @property
    def signer_keys(self) -> list["Pubkey"]:
        return self.to_message().signer_keys()

    @property
    def is_signed(self) -> bool:
        return all(str(signer) in self.signatures for signer in self.signer_keys)

    @property
    def txn_hash(self) -> HexBytes:
        if not (fee_payer_signature := self.signatures.get(str(self.fee_payer))):
            raise SignatureError("Transaction is not signed by its fee payer.", transaction=self)

        return HexBytes(bytes(to_signature(fee_payer_signature)))

    @property
    def transaction_id(self) -> str:
        """
        The base58 fee-payer signature explorers use to identify the transaction.
        """
        return str(Signature.from_bytes(bytes(self.txn_hash)))

    @property
    def total_transfer_value(self) -> int:
        return self.value + (self.max_fee or 0)

    def build_instructions(self) -> list[Instruction]:
        if not self.value:
            return list(self.instructions)

        if not self.receiver:
            raise TransactionError("Transaction has a `value` but no `receiver`.")

        transfer_params = TransferParams(
            from_pubkey=self.fee_payer,
            to_pubkey=to_pubkey(self.receiver),
            lamports=self.value,
        )
        return [transfer(transfer_params), *self.instructions]

    def to_message(self) -> Message:
        if not self.recent_blockhash:
            raise TransactionError("Transaction missing `recent_blockhash`. Prepare it first.")

        return Message.new_with_blockhash(
            self.build_instructions(), self.fee_payer, Hash.from_string(self.recent_blockhash)
        )

    def to_solders(self) -> Transaction:
        message = self.to_message()
        signatures = [
            (
                to_signature(self.signatures[str(signer)])
                if str(signer) in self.signatures
                else Signature.default()
            )
            for signer in message.signer_keys()
        ]
        return Transaction.populate(message, signatures)

    def add_signature(self, signer: "Pubkey", signature: Signature):
        self.signatures[str(signer)] = str(signature)

    def serialize_transaction(self) -> bytes:
        return bytes(self.to_solders())

    def to_string(self, calldata_repr=None) -> str:
        lines = [
            f"{type(self).__name__}:",
            f"  fee_payer: {self.sender}",
        ]
        if self.value:
            lines.append(f"  transfer: {self.value / LAMPORTS_PER_SOL} SOL to {self.receiver}")

        if self.recent_blockhash:
            lines.append(f"  recent_blockhash: {self.recent_blockhash}")

        if self.max_fee is not None:
            lines.append(f"  fee: {self.max_fee} lamports")

        for index, instruction in enumerate(self.instructions):
            lines.append(
                f"  instruction[{index}]: program={instruction.program_id} "
                f"accounts={len(instruction.accounts)} data=0x{bytes(instruction.data).hex()}"
            )

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} fee_payer={self.sender} "
            f"instructions={len(self.build_instructions())}>"
        )


class SolanaReceipt(ReceiptAPI):
    """
    The result of a processed Solana transaction. ``block_number`` is the slot and
    ``gas_used`` is the compute units consumed.
    """

    txn_hash: str
    fee: int = 0
    program_logs: list[str] = Field(default_factory=list)
    error_message: str | None = None

    @property
    def total_fees_paid(self) -> int:
        return self.fee

    @property
    def ran_out_of_gas(self) -> bool:
        return (
            self.error_message is not None and "ComputationalBudgetExceeded" in self.error_message
        )

    @property
    def failed(self) -> bool:
        return self.status != 1

    def raise_for_status(self):
        if not self.failed:
            return

        message = "\n".join([self.error_message or "Transaction failed.", *self.program_logs])
        raise TransactionError(message, txn=self)

    def await_confirmations(self) -> "SolanaReceipt":
        return self

    def decode_logs(
        self,
        abi: "list[EventABI | ContractEvent] | EventABI | ContractEvent | None" = None,
    ) -> "ContractLogContainer":
        # TODO: Decode Anchor events from `program_logs` once IDL support exists.
        raise APINotImplementedError("Event decoding is not yet supported on Solana.")

    def show_program_logs(self):
        for line in self.program_logs:
            click.echo(line)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.txn_hash}>"
