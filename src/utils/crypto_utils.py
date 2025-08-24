import os
import hashlib
import secrets
import string
INTERNAL_SALT = os.getenv('INTERNAL_SALT', '')

def generate_secret_key() -> str:
    key_chars = string.ascii_uppercase + string.digits
    random_part = ''.join((secrets.choice(key_chars) for _ in range(14)))
    return f'RUNE-{random_part}'

def hash_secret_key(secret_key: str) -> str:
    salted_key = (secret_key + INTERNAL_SALT).encode('utf-8')
    return hashlib.sha256(salted_key).hexdigest()

def possible_secret_hashes(secret_key: str) -> list[str]:
    hashes = []
    salted_key = (secret_key + INTERNAL_SALT).encode('utf-8')
    current = hashlib.sha256(salted_key).hexdigest()
    hashes.append(current)
    legacy_salt = 'deltahub_launcher_internal_secret'
    if INTERNAL_SALT != legacy_salt:
        legacy_salted_key = (secret_key + legacy_salt).encode('utf-8')
        hashes.append(hashlib.sha256(legacy_salted_key).hexdigest())
    return hashes

def verify_secret_key(entered_key: str, stored_hash: str) -> bool:
    return stored_hash in possible_secret_hashes(entered_key)