import json
from itertools import count

import ape
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from ape_solana.accounts import generate_account


@pytest.fixture(scope="session", autouse=True)
def isolated_data_folder():
    with ape.config.isolate_data_folder() as data_folder:
        yield data_folder


@pytest.fixture(scope="session")
def passphrase():
    return "a-Str0ng-passphrase!"


@pytest.fixture(scope="session")
def alias_counter():
    return count()


@pytest.fixture
def create_account(alias_counter, passphrase):
    created_accounts = []

    def create(autosign: bool = True):
        account, _ = generate_account(f"account{next(alias_counter)}", passphrase)
        if autosign:
            account.set_autosign(True, passphrase=passphrase)

        created_accounts.append(account)
        return account

    yield create

    for account in created_accounts:
        account.keyfile_path.unlink(missing_ok=True)


@pytest.fixture
def provider():
    with ape.networks.solana.local.use_provider("litesvm") as litesvm_provider:
        yield litesvm_provider


@pytest.fixture
def owner(create_account, provider):
    account = create_account()
    account.request_airdrop(10 * 10**9)
    return account


@pytest.fixture
def receiver():
    return Pubkey.new_unique()


@pytest.fixture(scope="session")
def keypair():
    return Keypair()


@pytest.fixture(scope="session")
def keypair_encodings(keypair):
    return {
        "json-array": json.dumps(list(bytes(keypair))),
        "base58": str(keypair),
        "hex-seed": keypair.secret().hex(),
        "hex-keypair": f"0x{bytes(keypair).hex()}",
    }
