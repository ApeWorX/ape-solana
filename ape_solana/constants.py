from ape.api.networks import LOCAL_NETWORK_NAME

ECOSYSTEM_NAME = "solana"
LAMPORTS_PER_SOL = 1_000_000_000
LAMPORTS_PER_SIGNATURE = 5_000
MAX_COMPUTE_UNITS = 1_400_000
SOLANA_DEFAULT_PATH = "m/44'/501'/0'/0'"

NETWORKS = {
    "mainnet": 101,
    "testnet": 102,
    "devnet": 103,
    LOCAL_NETWORK_NAME: 104,
}

PUBLIC_RPC_URIS = {
    "mainnet": "https://api.mainnet-beta.solana.com",
    "testnet": "https://api.testnet.solana.com",
    "devnet": "https://api.devnet.solana.com",
}

GENESIS_HASHES = {
    "mainnet": "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d",
    "testnet": "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY",
    "devnet": "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG",
}
