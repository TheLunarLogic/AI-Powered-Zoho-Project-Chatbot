"""Fernet encryption and decryption helpers."""

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401


def encrypt(plaintext: str, key: str) -> str:
    """Encrypt *plaintext* using the given Fernet *key*.

    Args:
        plaintext: The UTF-8 string to encrypt.
        key: A URL-safe base64-encoded 32-byte Fernet key
             (the exact format produced by ``Fernet.generate_key()``).

    Returns:
        A URL-safe base64-encoded ciphertext string.
    """
    fernet = Fernet(key.encode())
    token: bytes = fernet.encrypt(plaintext.encode())
    return token.decode()


def decrypt(ciphertext: str, key: str) -> str:
    """Decrypt *ciphertext* using the given Fernet *key*.

    Args:
        ciphertext: A URL-safe base64-encoded Fernet token string.
        key: A URL-safe base64-encoded 32-byte Fernet key.

    Returns:
        The original plaintext string.

    Raises:
        cryptography.fernet.InvalidToken: If *ciphertext* is invalid,
            tampered, or was encrypted with a different key.
    """
    fernet = Fernet(key.encode())
    plaintext_bytes: bytes = fernet.decrypt(ciphertext.encode())
    return plaintext_bytes.decode()
