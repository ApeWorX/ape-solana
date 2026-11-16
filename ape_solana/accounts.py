import json
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click
from ape.exceptions import AccountsError, SignatureError
from ape.logging import logger
from ape.types.address import AddressType
from ape.types.signatures import BaseSignature
from ape.utils.basemodel import ManagerAccessMixin
from ape_accounts.accounts import AccountContainer, BaseKeyfileAccount
from eth_account.hdaccount import Language, generate_mnemonic, seed_from_mnemonic
from eth_pydantic_types import HexBytes
from solders.keypair import Keypair
from solders.message import to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction, VersionedTransaction

from ape_solana.constants import ECOSYSTEM_NAME, LAMPORTS_PER_SOL, SOLANA_DEFAULT_PATH
from ape_solana.transactions import SolanaTransaction, to_signature

if TYPE_CHECKING:
    from ape.api.transactions import ReceiptAPI, TransactionAPI

SignableTransaction = SolanaTransaction | Transaction | VersionedTransaction

BaseSignature.register(Signature)


class SolanaAccountContainer(AccountContainer):
    @cached_property
    def data_folder(self) -> Path:
        path = self.config_manager.DATA_FOLDER / ECOSYSTEM_NAME / "accounts"
        path.mkdir(parents=True, exist_ok=True)
        return path


class SolanaAccount(BaseKeyfileAccount):
    """
    A Solana keypair stored in an encrypted keyfile.
    """

    passphrase_env_prefix = "APE_SOLANA_ACCOUNTS"
    __autosign: bool = False
    __cached_keypair: Keypair | None = None

    @classmethod
    def encrypt_secret(cls, secret: bytes, passphrase: str) -> dict:
        address = str(Keypair.from_seed(secret).pubkey())
        return {**super().encrypt_secret(secret, passphrase), "address": address}

    @property
    def address(self) -> AddressType:
        return cast(AddressType, self.keyfile["address"])

    @property
    def pubkey(self) -> Pubkey:
        return Pubkey.from_string(self.address)

    @property
    def public_key(self) -> HexBytes:
        return HexBytes(bytes(self.pubkey))

    @property
    def __keypair(self) -> Keypair:
        if self.__cached_keypair is not None:
            if not self.locked:
                logger.warning("Using cached key for %s", self.alias)
                return self.__cached_keypair

            self.__cached_keypair = None

        passphrase = self._prompt_for_passphrase(default="")
        keypair = Keypair.from_seed(self._decrypt_keyfile(passphrase))
        if click.confirm(f"Leave '{self.alias}' unlocked?"):
            self.locked = False
            self.__cached_keypair = keypair

        return keypair

    def unlock(self, passphrase: str | None = None):
        self.__cached_keypair = Keypair.from_seed(self._request_secret(passphrase))
        self.locked = False

    def change_password(self):
        self.locked = True
        keypair = self.__keypair
        passphrase = self._prompt_for_passphrase("Create new passphrase", confirmation_prompt=True)
        self.write_keyfile(self.keyfile_path, keypair.secret(), passphrase)

    def set_autosign(self, enabled: bool, passphrase: str | None = None):
        """
        Allow this account to sign messages and transactions without prompting.

        Args:
            enabled (bool): ``True`` to enable, ``False`` to disable.
            passphrase (str | None): The passphrase, prompted for when not given.
        """
        if enabled:
            self.unlock(passphrase=passphrase)
            logger.warning("Danger! This account will now sign any transaction it's given.")

        self.__autosign = enabled
        if not enabled:
            self.locked = True
            self.__cached_keypair = None

    # TODO: In ape 0.9, drop the `type: ignore` once `sign_message` returns `BaseSignature`.
    def sign_message(  # type: ignore[override]
        self, msg: Any, **signer_options
    ) -> Signature | None:
        if isinstance(msg, str):
            display_msg = f"Signing raw string: '{msg}'"
            msg = msg.encode("utf8")

        elif isinstance(msg, bytes):
            display_msg = f"Signing raw bytes: '0x{msg.hex()}'"

        else:
            logger.warning("Unsupported message type, (type=%r, msg=%r)", type(msg), msg)
            return None

        if not (self.__autosign or click.confirm(f"{display_msg}\n\nSign: ")):
            return None

        return self.__keypair.sign_message(msg)

    def sign_transaction(  # type: ignore[override]
        self, txn: "TransactionAPI | SignableTransaction", **signer_options
    ) -> "TransactionAPI | SignableTransaction | None":
        if not (self.__autosign or click.confirm(f"{txn}\n\nSign: ")):
            return None

        return sign_transaction_with_keypair(self.__keypair, txn)

    def check_signature(  # type: ignore[override]
        self,
        data: "str | bytes | SignableTransaction",
        signature: BaseSignature | bytes | None = None,
        recover_using_eip191: bool = True,
    ) -> bool:
        if isinstance(data, SolanaTransaction):
            if not (signature_str := data.signatures.get(self.address)):
                return False

            return to_signature(signature_str).verify(self.pubkey, bytes(data.to_message()))

        if isinstance(data, (Transaction, VersionedTransaction)):
            signed_message = get_signed_message_bytes(data)
            signer_index = find_signer_index(data, self.pubkey)
            return data.signatures[signer_index].verify(self.pubkey, signed_message)

        if signature is None:
            raise AccountsError("Parameter 'signature' required when verifying a message.")

        message_bytes = data.encode("utf8") if isinstance(data, str) else data
        return Signature.from_bytes(bytes(signature)).verify(self.pubkey, message_bytes)

    def prepare_transaction(self, txn: "TransactionAPI", **kwargs) -> "TransactionAPI":
        sign = kwargs.pop("sign", False)
        txn.sender = txn.sender or self.address
        prepared_txn = self.provider.prepare_transaction(txn)
        if prepared_txn.total_transfer_value > self.balance:
            raise AccountsError(
                f"Transfer value meets or exceeds account balance for account '{self.address}' "
                f"(transfer_value={prepared_txn.total_transfer_value}, balance={self.balance})."
            )

        if not sign:
            return prepared_txn

        return self.sign_transaction(prepared_txn) or prepared_txn  # type: ignore[return-value]

    def call(  # type: ignore[override]
        self,
        txn: "TransactionAPI",
        send_everything: bool = False,
        private: bool = False,
        sign: bool = True,
        **signer_options,
    ) -> "ReceiptAPI":
        if send_everything:
            txn.sender = txn.sender or self.address
            txn.value = 0
            txn = self.provider.prepare_transaction(txn)
            txn.value = self.balance - (txn.max_fee or 0)
            if txn.value <= 0:
                raise AccountsError("Sender does not have enough to cover the transaction fee.")

        prepared_txn = self.prepare_transaction(txn)
        if sign:
            signed_txn = self.sign_transaction(prepared_txn, **signer_options)
            if not signed_txn:
                raise SignatureError("The transaction was not signed.", transaction=prepared_txn)

            prepared_txn = signed_txn  # type: ignore[assignment]

        return self.provider.send_transaction(prepared_txn)

    def request_airdrop(self, lamports: int = LAMPORTS_PER_SOL) -> str:
        """
        Fund this account on a test network, returning the airdrop transaction signature.
        """
        return self.provider.request_airdrop(self.address, lamports)  # type: ignore[attr-defined]


def get_signed_message_bytes(transaction: Transaction | VersionedTransaction) -> bytes:
    if isinstance(transaction, Transaction):
        return bytes(transaction.message)

    return to_bytes_versioned(transaction.message)


def find_signer_index(transaction: Transaction | VersionedTransaction, signer: Pubkey) -> int:
    message = transaction.message
    signer_keys = message.account_keys[: message.header.num_required_signatures]
    if signer not in signer_keys:
        raise SignatureError(f"'{signer}' is not a required signer of this transaction.")

    return signer_keys.index(signer)


def sign_transaction_with_keypair(
    keypair: Keypair, txn: "TransactionAPI | SignableTransaction"
) -> "SolanaTransaction | Transaction | VersionedTransaction":
    """
    Add ``keypair``'s signature to an ape ``SolanaTransaction`` or a ``solders`` transaction.
    """
    if isinstance(txn, SolanaTransaction):
        message = txn.to_message()
        if keypair.pubkey() not in message.signer_keys():
            raise SignatureError(f"'{keypair.pubkey()}' is not a required signer.", transaction=txn)

        txn.add_signature(keypair.pubkey(), keypair.sign_message(bytes(message)))
        return txn

    if isinstance(txn, (Transaction, VersionedTransaction)):
        signer_index = find_signer_index(txn, keypair.pubkey())
        signatures = list(txn.signatures)
        signatures[signer_index] = keypair.sign_message(get_signed_message_bytes(txn))
        if isinstance(txn, Transaction):
            return Transaction.populate(txn.message, signatures)

        return VersionedTransaction.populate(txn.message, signatures)

    raise SignatureError(f"Unable to sign transaction of type '{type(txn).__name__}'.")


def load_keypair(private_key: str) -> Keypair:
    """
    Parse a secret key as a ``solana-keygen`` JSON byte array, base58 (Phantom export), or hex.
    """
    value = private_key.strip()
    if value.startswith("["):
        return create_keypair_from_bytes(bytes(json.loads(value)))

    hex_value = value.removeprefix("0x")
    if len(hex_value) in (64, 128) and all(char in "0123456789abcdefABCDEF" for char in hex_value):
        return create_keypair_from_bytes(bytes.fromhex(hex_value))

    return Keypair.from_base58_string(value)


def create_keypair_from_bytes(secret: bytes) -> Keypair:
    if len(secret) == 32:
        return Keypair.from_seed(secret)

    if len(secret) == 64:
        return Keypair.from_bytes(secret)

    raise AccountsError(f"Expected a 32 or 64 byte secret key, got {len(secret)} bytes.")


def _write_and_return_account(alias: str, passphrase: str, keypair: Keypair) -> SolanaAccount:
    container = ManagerAccessMixin.account_manager.containers[ECOSYSTEM_NAME]
    return cast(SolanaAccount, container.create_account(alias, passphrase, keypair.secret()))


def generate_account(
    alias: str, passphrase: str, hd_path: str = SOLANA_DEFAULT_PATH, word_count: int = 12
) -> tuple[SolanaAccount, str]:
    """
    Generate a new account from a random mnemonic.

    Args:
        alias (str): The alias of the account.
        passphrase (str): Passphrase used to encrypt the keyfile.
        hd_path (str): The derivation path. Defaults to ``m/44'/501'/0'/0'`` (Phantom, Solflare).
        word_count (int): The number of words in the generated mnemonic.

    Returns:
        The new :class:`~ape_solana.accounts.SolanaAccount` and its mnemonic.
    """
    mnemonic = generate_mnemonic(word_count, Language.ENGLISH)
    account = import_account_from_mnemonic(alias, passphrase, mnemonic, hd_path=hd_path)
    return account, mnemonic


def import_account_from_mnemonic(
    alias: str, passphrase: str, mnemonic: str, hd_path: str = SOLANA_DEFAULT_PATH
) -> SolanaAccount:
    seed = seed_from_mnemonic(mnemonic, "")
    keypair = Keypair.from_seed_and_derivation_path(seed, hd_path)
    return _write_and_return_account(alias, passphrase, keypair)


def import_account_from_private_key(alias: str, passphrase: str, private_key: str) -> SolanaAccount:
    return _write_and_return_account(alias, passphrase, load_keypair(private_key))


def import_account_from_keypair_file(alias: str, passphrase: str, path: Path) -> SolanaAccount:
    """
    Import a ``solana-keygen`` keypair file, such as ``~/.config/solana/id.json``.
    """
    return import_account_from_private_key(alias, passphrase, path.read_text())
