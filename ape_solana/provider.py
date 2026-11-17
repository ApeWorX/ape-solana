import base64
import time
from abc import abstractmethod
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any, ClassVar

import requests
from ape.api.providers import ProviderAPI
from ape.exceptions import (
    APINotImplementedError,
    BlockNotFoundError,
    ProviderError,
    ProviderNotConnectedError,
    TransactionError,
    TransactionNotFoundError,
)
from solders.hash import Hash
from solders.litesvm import LiteSVM
from solders.signature import Signature
from solders.transaction import Transaction, VersionedTransaction
from solders.transaction_metadata import FailedTransactionMetadata

from ape_solana._converters import to_pubkey
from ape_solana.constants import (
    GENESIS_HASHES,
    LAMPORTS_PER_SIGNATURE,
    MAX_COMPUTE_UNITS,
    PUBLIC_RPC_URIS,
)
from ape_solana.ecosystem import SolanaBlock
from ape_solana.transactions import SolanaReceipt, SolanaTransaction, to_signature

if TYPE_CHECKING:
    from ape.api.transactions import TransactionAPI
    from ape.types import BlockID, ContractLog, LogFilter
    from ape.types.address import AddressType
    from ape.types.vm import ContractCode

LOCAL_RPC_URI = "http://127.0.0.1:8899"
BLOCK_TAGS = ("latest", "pending", "earliest")
MAX_SUPPORTED_TRANSACTION_VERSION = 1
CONFIRMATION_POLL_INTERVAL_SECONDS = 0.5
LATEST_BLOCK_LOOKBACK_SLOTS = 10
ACCEPTED_CONFIRMATION_STATUSES = {
    "processed": ("processed", "confirmed", "finalized"),
    "confirmed": ("confirmed", "finalized"),
    "finalized": ("finalized",),
}


class SolanaRpcError(ProviderError):
    def __init__(self, message: str, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class SolanaProvider(ProviderAPI):
    """
    Behavior shared by every Solana provider.
    """

    _slot_by_blockhash: dict[str, int] = {}

    def __repr__(self) -> str:
        return f"<{self.name} {self.network.choice}>"

    def __str__(self) -> str:
        return repr(self)

    @property
    def chain_id(self) -> int:
        return self.network.chain_id

    @property
    def commitment(self) -> str:
        return self.network.config.get("commitment", "confirmed")

    @property
    def gas_price(self) -> int:
        return LAMPORTS_PER_SIGNATURE

    @property
    def max_gas(self) -> int:
        return MAX_COMPUTE_UNITS

    def update_settings(self, new_settings: dict):
        self.disconnect()
        self.provider_settings.update(new_settings)
        self.connect()

    def get_nonce(self, address: "AddressType", block_id: "BlockID | None" = None) -> int:
        return 0

    def estimate_gas_cost(self, txn: "TransactionAPI", block_id: "BlockID | None" = None) -> int:
        return LAMPORTS_PER_SIGNATURE * len(require_solana_transaction(txn).signer_keys)

    def prepare_transaction(self, txn: "TransactionAPI") -> SolanaTransaction:
        solana_txn = require_solana_transaction(txn)
        if not solana_txn.recent_blockhash:
            solana_txn.recent_blockhash = self.get_latest_blockhash()

        if solana_txn.max_fee is None:
            solana_txn.max_fee = self.estimate_gas_cost(solana_txn)

        if solana_txn.gas_limit is None:
            solana_txn.gas_limit = self.max_gas

        return solana_txn

    def send_call(
        self,
        txn: "TransactionAPI",
        block_id: "BlockID | None" = None,
        state: dict | None = None,
        **kwargs,
    ) -> bytes:
        # TODO: Map read-only calls onto `simulateTransaction` return data.
        raise APINotImplementedError("Read-only calls are not yet supported on Solana.")

    def get_contract_logs(self, log_filter: "LogFilter") -> Iterator["ContractLog"]:
        # TODO: Query program logs with `getSignaturesForAddress`.
        raise APINotImplementedError("Log queries are not yet supported on Solana.")

    def get_block(self, block_id: "BlockID") -> SolanaBlock:
        blockhash = str(Hash(bytes(block_id))) if isinstance(block_id, bytes) else block_id
        if isinstance(blockhash, str) and blockhash not in BLOCK_TAGS:
            if (slot := self._slot_by_blockhash.get(blockhash)) is None:
                raise BlockNotFoundError(block_id, reason="Solana looks up blocks by slot.")

            block_id = slot

        block = self.fetch_block(block_id)
        if block.hash:
            self._slot_by_blockhash[block.hash] = block.number

        return block

    @abstractmethod
    def fetch_block(self, block_id: "BlockID") -> SolanaBlock:
        """
        The block at a slot or at a tag such as ``"latest"``.
        """

    @abstractmethod
    def get_latest_blockhash(self) -> str:
        """
        The blockhash new transactions should reference.
        """

    @abstractmethod
    def request_airdrop(self, address: "AddressType", lamports: int) -> str:
        """
        Fund ``address`` with ``lamports`` and return the airdrop transaction signature.
        """

    def create_receipt(self, transaction: SolanaTransaction, **fields) -> SolanaReceipt:
        return SolanaReceipt.model_validate(
            {"gas_used": 0, "logs": [], "transaction": transaction, **fields}
        )


class SolanaRpcProvider(SolanaProvider):
    """
    A provider talking to a Solana JSON-RPC node.
    """

    NAME: ClassVar[str] = "solana"

    _session: requests.Session | None = None
    _request_id: int = 0

    @property
    def uri(self) -> str:
        if uri := self.provider_settings.get("uri") or self.network.config.get("uri"):
            return uri

        return PUBLIC_RPC_URIS.get(self.network.name, LOCAL_RPC_URI)

    @property
    def http_uri(self) -> str:
        return self.uri

    @property
    def connection_str(self) -> str:
        return self.uri

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    def connect(self):
        self._session = requests.Session()
        self._session.headers.update({**self.request_header, "Content-Type": "application/json"})
        expected_genesis_hash = GENESIS_HASHES.get(self.network.name)
        if expected_genesis_hash is None:
            return

        genesis_hash = self.make_request("getGenesisHash")
        if genesis_hash != expected_genesis_hash:
            self.disconnect()
            raise ProviderError(
                f"RPC at '{self.uri}' is not Solana {self.network.name} "
                f"(genesis hash {genesis_hash})."
            )

    def disconnect(self):
        if self._session is not None:
            self._session.close()

        self._session = None

    def make_request(self, rpc: str, parameters: Iterable | None = None) -> Any:
        if self._session is None:
            raise ProviderNotConnectedError()

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": rpc,
            "params": list(parameters or []),
        }
        response = self._session.post(self.uri, json=payload, timeout=30)
        if not response.ok:
            raise SolanaRpcError(
                f"{rpc} failed: HTTP {response.status_code} {response.text.strip()}"
            )

        response_data = response.json()
        if error := response_data.get("error"):
            raise SolanaRpcError(
                error.get("message", f"{rpc} failed."), error.get("code"), error.get("data")
            )

        return response_data.get("result")

    def get_balance(self, address: "AddressType", block_id: "BlockID | None" = None) -> int:
        result = self.make_request("getBalance", [str(address), {"commitment": self.commitment}])
        return result["value"]

    def get_code(self, address: "AddressType", block_id: "BlockID | None" = None) -> "ContractCode":
        account_info = self.make_request(
            "getAccountInfo",
            [str(address), {"encoding": "base64", "commitment": self.commitment}],
        )["value"]
        if not account_info or not account_info["executable"]:
            return b""

        return base64.b64decode(account_info["data"][0])

    def get_latest_blockhash(self) -> str:
        result = self.make_request("getLatestBlockhash", [{"commitment": self.commitment}])
        return result["value"]["blockhash"]

    def estimate_gas_cost(self, txn: "TransactionAPI", block_id: "BlockID | None" = None) -> int:
        solana_txn = require_solana_transaction(txn)
        if not solana_txn.recent_blockhash:
            return super().estimate_gas_cost(solana_txn)

        encoded_message = base64.b64encode(bytes(solana_txn.to_message())).decode()
        result = self.make_request(
            "getFeeForMessage", [encoded_message, {"commitment": self.commitment}]
        )
        fee = result["value"]
        return super().estimate_gas_cost(solana_txn) if fee is None else fee

    def fetch_block(self, block_id: "BlockID") -> SolanaBlock:
        if block_id in ("latest", "pending"):
            return self._get_latest_block()

        if block_id == "earliest":
            return self._get_block_at_slot(self.make_request("getFirstAvailableBlock"))

        if isinstance(block_id, int):
            return self._get_block_at_slot(block_id)

        raise BlockNotFoundError(block_id, reason="Solana blocks are looked up by slot.")

    def _get_latest_block(self) -> SolanaBlock:
        slot = self.make_request("getSlot", [{"commitment": "confirmed"}])
        for candidate_slot in range(slot, slot - LATEST_BLOCK_LOOKBACK_SLOTS, -1):
            try:
                return self._get_block_at_slot(candidate_slot)
            except BlockNotFoundError:
                continue

        raise BlockNotFoundError("latest")

    def _get_block_at_slot(self, slot: int) -> SolanaBlock:
        block_data = self._request_block(slot, transaction_details="signatures")
        return SolanaBlock(
            number=slot,
            hash=block_data["blockhash"],
            parentHash=block_data["previousBlockhash"],
            timestamp=block_data.get("blockTime") or 0,
            num_transactions=len(block_data.get("signatures", [])),
        )

    def _request_block(self, slot: int, transaction_details: str) -> dict:
        block_options = {
            "commitment": "confirmed",
            "encoding": "base64",
            "transactionDetails": transaction_details,
            "rewards": False,
            "maxSupportedTransactionVersion": MAX_SUPPORTED_TRANSACTION_VERSION,
        }
        try:
            block_data = self.make_request("getBlock", [slot, block_options])
        except SolanaRpcError as err:
            raise BlockNotFoundError(slot, reason=str(err)) from err

        if block_data is None:
            raise BlockNotFoundError(slot)

        return block_data

    def get_transactions_by_block(self, block_id: "BlockID") -> Iterator[SolanaTransaction]:
        slot = self.get_block(block_id).number
        block_data = self._request_block(slot, transaction_details="full")
        for transaction_data in block_data.get("transactions", []):
            yield decode_rpc_transaction(transaction_data)

    def send_transaction(self, txn: "TransactionAPI") -> SolanaReceipt:
        solana_txn = require_solana_transaction(txn)
        encoded_transaction = base64.b64encode(solana_txn.serialize_transaction()).decode()
        send_options = {"encoding": "base64", "preflightCommitment": self.commitment}
        try:
            transaction_id = self.make_request(
                "sendTransaction", [encoded_transaction, send_options]
            )
        except SolanaRpcError as err:
            program_logs = (err.data or {}).get("logs") or []
            message = "\n".join([str(err), *program_logs])
            raise TransactionError(message, base_err=err, txn=solana_txn) from err

        self._await_signature_status(transaction_id)
        receipt = self.get_receipt(transaction_id, transaction=solana_txn)
        if solana_txn.raise_on_revert:
            receipt.raise_for_status()

        return receipt

    def _await_signature_status(self, transaction_id: str):
        accepted_statuses = ACCEPTED_CONFIRMATION_STATUSES[self.commitment]
        deadline = time.monotonic() + self.network.transaction_acceptance_timeout
        while time.monotonic() < deadline:
            statuses = self.make_request("getSignatureStatuses", [[transaction_id]])["value"]
            if (status := statuses[0]) and status.get("confirmationStatus") in accepted_statuses:
                return

            time.sleep(CONFIRMATION_POLL_INTERVAL_SECONDS)

        raise TransactionNotFoundError(
            transaction_hash=transaction_id,
            error_message=f"Transaction not {self.commitment} before timeout.",
        )

    def get_receipt(self, txn_hash: str, **kwargs) -> SolanaReceipt:
        transaction_id = str(to_signature(txn_hash))
        commitment = "finalized" if self.commitment == "finalized" else "confirmed"
        transaction_options = {
            "encoding": "base64",
            "commitment": commitment,
            "maxSupportedTransactionVersion": MAX_SUPPORTED_TRANSACTION_VERSION,
        }
        transaction_data = self.make_request(
            "getTransaction", [transaction_id, transaction_options]
        )
        if transaction_data is None:
            raise TransactionNotFoundError(transaction_hash=transaction_id)

        transaction = kwargs.get("transaction") or decode_rpc_transaction(transaction_data)
        meta = transaction_data["meta"] or {}
        error = meta.get("err")
        return self.create_receipt(
            transaction,
            txn_hash=transaction_id,
            block_number=transaction_data["slot"],
            gas_used=meta.get("computeUnitsConsumed") or 0,
            status=0 if error else 1,
            fee=meta.get("fee") or 0,
            program_logs=meta.get("logMessages") or [],
            error_message=str(error) if error else None,
        )

    def request_airdrop(self, address: "AddressType", lamports: int) -> str:
        transaction_id = self.make_request(
            "requestAirdrop", [str(address), lamports, {"commitment": self.commitment}]
        )
        self._await_signature_status(transaction_id)
        return transaction_id


def decode_rpc_transaction(transaction_data: dict) -> SolanaTransaction:
    raw_transaction = base64.b64decode(transaction_data["transaction"][0])
    if transaction_data.get("version", "legacy") == "legacy":
        return SolanaTransaction.from_solders(Transaction.from_bytes(raw_transaction))

    versioned_transaction = VersionedTransaction.from_bytes(raw_transaction)
    if legacy_transaction := versioned_transaction.into_legacy_transaction():
        return SolanaTransaction.from_solders(legacy_transaction)

    # TODO: Model v0 transactions with address lookup tables.
    fee_payer = versioned_transaction.message.account_keys[0]
    return SolanaTransaction(sender=str(fee_payer))


class LiteSVMProvider(SolanaProvider):
    """
    An in-process Solana VM for local development and testing.
    """

    NAME: ClassVar[str] = "litesvm"

    _svm: LiteSVM | None = None
    _receipts: dict[str, SolanaReceipt] = {}
    _mined_blocks: dict[int, SolanaBlock] = {}

    @property
    def svm(self) -> LiteSVM:
        if self._svm is None:
            raise ProviderNotConnectedError()

        return self._svm

    @property
    def is_connected(self) -> bool:
        return self._svm is not None

    def connect(self):
        self._svm = LiteSVM()
        self._receipts = {}
        self._mined_blocks = {}
        self._slot_by_blockhash = {}

    def disconnect(self):
        self._svm = None
        self._receipts = {}
        self._mined_blocks = {}
        self._slot_by_blockhash = {}

    def make_request(self, rpc: str, parameters: Iterable | None = None) -> Any:
        raise APINotImplementedError("LiteSVM is in-process and has no JSON-RPC interface.")

    def get_balance(self, address: "AddressType", block_id: "BlockID | None" = None) -> int:
        return self.svm.get_balance(to_pubkey(address)) or 0

    def get_code(self, address: "AddressType", block_id: "BlockID | None" = None) -> "ContractCode":
        account = self.svm.get_account(to_pubkey(address))
        if account is None or not account.executable:
            return b""

        return bytes(account.data)

    def get_latest_blockhash(self) -> str:
        return str(self.svm.latest_blockhash())

    def fetch_block(self, block_id: "BlockID") -> SolanaBlock:
        clock = self.svm.get_clock()
        if block_id in ("latest", "pending", clock.slot):
            return self._create_current_block()

        if block_id == "earliest":
            block_id = min(self._mined_blocks, default=clock.slot)

        if block := self._mined_blocks.get(block_id):  # type: ignore[arg-type]
            return block

        raise BlockNotFoundError(block_id, reason="No transactions were processed at this slot.")

    def _create_current_block(self) -> SolanaBlock:
        clock = self.svm.get_clock()
        return SolanaBlock(
            number=clock.slot,
            hash=self.get_latest_blockhash(),
            timestamp=clock.unix_timestamp,
            num_transactions=len(self._get_receipts_at_slot(clock.slot)),
        )

    def _get_receipts_at_slot(self, slot: int) -> list[SolanaReceipt]:
        return [receipt for receipt in self._receipts.values() if receipt.block_number == slot]

    def get_transactions_by_block(self, block_id: "BlockID") -> Iterator["TransactionAPI"]:
        slot = self.get_block(block_id).number
        for receipt in self._get_receipts_at_slot(slot):
            yield receipt.transaction

    def send_transaction(self, txn: "TransactionAPI") -> SolanaReceipt:
        solana_txn = require_solana_transaction(txn)
        result = self.svm.send_transaction(solana_txn.to_solders())
        if isinstance(result, FailedTransactionMetadata):
            metadata = result.meta()
            error_message: str | None = str(result.err())
        else:
            metadata = result
            error_message = None

        transaction_id = str(metadata.signature())
        if transaction_id == str(Signature.default()):
            transaction_id = solana_txn.transaction_id

        receipt = self.create_receipt(
            solana_txn,
            txn_hash=transaction_id,
            block_number=self.svm.get_clock().slot,
            gas_used=metadata.compute_units_consumed(),
            status=int(error_message is None),
            fee=metadata.fee(),
            program_logs=list(metadata.logs()),
            error_message=error_message,
        )
        self._receipts[transaction_id] = receipt
        self.mine()
        if solana_txn.raise_on_revert:
            receipt.raise_for_status()

        return receipt

    def get_receipt(self, txn_hash: str, **kwargs) -> SolanaReceipt:
        transaction_id = str(to_signature(txn_hash))
        if receipt := self._receipts.get(transaction_id):
            return receipt

        raise TransactionNotFoundError(transaction_hash=transaction_id)

    def request_airdrop(self, address: "AddressType", lamports: int) -> str:
        result = self.svm.airdrop(to_pubkey(address), lamports)
        if isinstance(result, FailedTransactionMetadata):
            raise ProviderError(f"Airdrop failed: {result.err()}")

        return str(result.signature())

    def mine(self, num_blocks: int = 1):
        current_block = self._create_current_block()
        self._mined_blocks[current_block.number] = current_block
        if current_block.hash:
            self._slot_by_blockhash[current_block.hash] = current_block.number

        self.svm.warp_to_slot(self.svm.get_clock().slot + num_blocks)
        self.svm.expire_blockhash()

    def set_timestamp(self, new_timestamp: int):
        clock = self.svm.get_clock()
        clock.unix_timestamp = new_timestamp
        self.svm.set_clock(clock)


def require_solana_transaction(txn: "TransactionAPI") -> SolanaTransaction:
    if not isinstance(txn, SolanaTransaction):
        raise TransactionError(f"Expected a SolanaTransaction, got '{type(txn).__name__}'.")

    return txn
