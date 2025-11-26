import binascii
import os
import secrets


def generate_crypto_id(byte_length: int = 16) -> str:
    """Generate a random cryptographic ID.

    Args:
        byte_length (int): The number of random bytes to generate. Defaults to 16.

    Returns:
        str: A hexadecimal string representation of the random bytes.
    """
    random_bytes = os.urandom(byte_length)
    crypto_id = binascii.hexlify(random_bytes).decode("utf-8")
    return crypto_id


def generate_session_id() -> str:
    # 128-bit random hex string
    return secrets.token_hex(16)
