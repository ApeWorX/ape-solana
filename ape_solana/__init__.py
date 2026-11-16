from importlib import import_module

from ape import plugins


@plugins.register(plugins.Config)
def config_class():
    from ape_solana.config import SolanaConfig

    return SolanaConfig


@plugins.register(plugins.ConversionPlugin)
def converters():
    from ape.types.address import AddressType

    from ape_solana._converters import SolanaAddressConverter

    yield AddressType, SolanaAddressConverter


@plugins.register(plugins.EcosystemPlugin)
def ecosystems():
    from ape_solana.ecosystem import Solana

    yield Solana


@plugins.register(plugins.NetworkPlugin)
def networks():
    from ape.api.networks import create_network_type

    from ape_solana.constants import ECOSYSTEM_NAME, NETWORKS

    for network_name, chain_id in NETWORKS.items():
        yield ECOSYSTEM_NAME, network_name, create_network_type(chain_id, chain_id)


@plugins.register(plugins.ProviderPlugin)
def providers():
    from ape.api.networks import LOCAL_NETWORK_NAME

    from ape_solana.constants import ECOSYSTEM_NAME, NETWORKS
    from ape_solana.provider import LiteSVMProvider, SolanaRpcProvider

    for network_name in NETWORKS:
        yield ECOSYSTEM_NAME, network_name, SolanaRpcProvider

    yield ECOSYSTEM_NAME, LOCAL_NETWORK_NAME, LiteSVMProvider


@plugins.register(plugins.AccountPlugin)
def account_types():
    from ape_solana.accounts import SolanaAccount, SolanaAccountContainer

    return SolanaAccountContainer, SolanaAccount


MODULE_BY_ATTRIBUTE = {
    "LiteSVMProvider": "ape_solana.provider",
    "Solana": "ape_solana.ecosystem",
    "SolanaAccount": "ape_solana.accounts",
    "SolanaAccountContainer": "ape_solana.accounts",
    "SolanaConfig": "ape_solana.config",
    "SolanaReceipt": "ape_solana.transactions",
    "SolanaRpcProvider": "ape_solana.provider",
    "SolanaTransaction": "ape_solana.transactions",
    "generate_account": "ape_solana.accounts",
    "import_account_from_keypair_file": "ape_solana.accounts",
    "import_account_from_mnemonic": "ape_solana.accounts",
    "import_account_from_private_key": "ape_solana.accounts",
}


def __getattr__(name: str):
    if module_path := MODULE_BY_ATTRIBUTE.get(name):
        return getattr(import_module(module_path), name)

    raise AttributeError(name)


__all__ = [*MODULE_BY_ATTRIBUTE]
