import os
from dataclasses import dataclass


@dataclass
class BlockchainConfig:
    provider_url: str
    private_key: str
    from_address: str
    network_name: str


def load_blockchain_config(secrets=None) -> BlockchainConfig:
    """Carga configuración blockchain desde env o secrets de Streamlit."""
    secrets = secrets or {}

    provider_url = os.getenv("BLOCKCHAIN_PROVIDER_URL", "") or str(secrets.get("BLOCKCHAIN_PROVIDER_URL", ""))
    private_key = os.getenv("BLOCKCHAIN_PRIVATE_KEY", "") or str(secrets.get("BLOCKCHAIN_PRIVATE_KEY", ""))
    from_address = os.getenv("BLOCKCHAIN_FROM_ADDRESS", "") or str(secrets.get("BLOCKCHAIN_FROM_ADDRESS", ""))
    network_name = os.getenv("BLOCKCHAIN_NETWORK", "sepolia") or str(secrets.get("BLOCKCHAIN_NETWORK", "sepolia"))

    return BlockchainConfig(
        provider_url=provider_url.strip(),
        private_key=private_key.strip(),
        from_address=from_address.strip(),
        network_name=network_name.strip(),
    )


def is_blockchain_configured(config: BlockchainConfig) -> bool:
    return bool(config.provider_url and config.private_key and config.from_address)


def anchor_hash_in_blockchain(interaction_hash: str, config: BlockchainConfig) -> str:
    """
    Ancla un hash en blockchain enviando una tx 0 ETH con el hash en `data`.

    Retorna `tx_hash` hexadecimal.
    """
    if not interaction_hash:
        raise ValueError("interaction_hash vacío")
    if not is_blockchain_configured(config):
        raise ValueError("Configuración blockchain incompleta")

    from web3 import Web3

    web3 = Web3(Web3.HTTPProvider(config.provider_url))
    if not web3.is_connected():
        raise RuntimeError("No se pudo conectar al proveedor blockchain")

    from_checksum = web3.to_checksum_address(config.from_address)
    nonce = web3.eth.get_transaction_count(from_checksum)
    gas_price = web3.eth.gas_price

    tx = {
        "nonce": nonce,
        "to": from_checksum,
        "value": 0,
        "gas": 100000,
        "gasPrice": gas_price,
        "data": web3.to_hex(text=interaction_hash),
        "chainId": web3.eth.chain_id,
    }

    signed = web3.eth.account.sign_transaction(tx, private_key=config.private_key)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    return web3.to_hex(tx_hash)
