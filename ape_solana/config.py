from typing import Literal

from ape.api.config import PluginConfig
from ape.api.networks import LOCAL_NETWORK_NAME
from pydantic import Field
from pydantic_settings import SettingsConfigDict

Commitment = Literal["processed", "confirmed", "finalized"]


class SolanaNetworkConfig(PluginConfig):
    uri: str | None = None
    commitment: Commitment = "confirmed"
    required_confirmations: int = 0
    block_time: int = 1
    transaction_acceptance_timeout: int = 60
    default_provider: str = "solana"


def create_local_network_config() -> SolanaNetworkConfig:
    return SolanaNetworkConfig(
        block_time=0, transaction_acceptance_timeout=20, default_provider="litesvm"
    )


class SolanaConfig(PluginConfig):
    mainnet: SolanaNetworkConfig = Field(default_factory=SolanaNetworkConfig)
    testnet: SolanaNetworkConfig = Field(default_factory=SolanaNetworkConfig)
    devnet: SolanaNetworkConfig = Field(default_factory=SolanaNetworkConfig)
    local: SolanaNetworkConfig = Field(default_factory=create_local_network_config)
    default_network: str = LOCAL_NETWORK_NAME

    model_config = SettingsConfigDict(extra="allow", env_prefix="APE_SOLANA_")
