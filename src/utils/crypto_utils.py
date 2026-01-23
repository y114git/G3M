"""Cryptographic utilities.

This module provides utilities for hashing, encryption, and secure random generation.
"""
import os
import hashlib
import secrets
import string
INTERNAL_SALT = os.getenv('INTERNAL_SALT', '')


def generate_secret_key() -> str:
    """Generate a random secret key for authentication.

    Returns:
        str: Generated secret key in format 'RUNE-XXXXXXXXXXXXXX'.
    """
    key_chars = string.ascii_uppercase + string.digits
    random_part = ''.join((secrets.choice(key_chars) for _ in range(14)))
    return f'RUNE-{random_part}'


def hash_secret_key(secret_key: str) -> str:
    """Hash a secret key with internal salt using SHA-256.

    Args:
        secret_key: Secret key to hash.

    Returns:
        str: SHA-256 hash of the salted key.
    """
    salted_key = (secret_key + INTERNAL_SALT).encode('utf-8')
    return hashlib.sha256(salted_key).hexdigest()


def possible_secret_hashes(secret_key: str) -> list[str]:
    """Generate all possible hashes for a secret key including legacy versions.

    Args:
        secret_key: Secret key to hash.

    Returns:
        list[str]: List of possible hashes (current and legacy).
    """
    salted_key = (secret_key + INTERNAL_SALT).encode('utf-8')
    current = hashlib.sha256(salted_key).hexdigest()
    hashes = [current]
    legacy_salt = 'deltahub_launcher_internal_secret'
    if INTERNAL_SALT != legacy_salt:
        legacy_salted_key = (secret_key + legacy_salt).encode('utf-8')
        hashes.append(hashlib.sha256(legacy_salted_key).hexdigest())
    return hashes
