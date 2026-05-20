import base64
import hashlib
import hmac
import os
import secrets
import json
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from passlib.context import CryptContext

# Password hashing with Argon2id
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain text password against its Argon2id hash."""
    return pwd_context.verify(plain, hashed)


# AES-256-GCM encryption for sensitive fields
def encrypt_field(plaintext: str, key: bytes) -> str:
    """Encrypt a field using AES-256-GCM. Returns base64-encoded nonce+ciphertext."""
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes for AES-256")
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode("utf-8")


def decrypt_field(ciphertext_b64: str, key: bytes) -> str:
    """Decrypt a field encrypted with AES-256-GCM."""
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes for AES-256")
    aesgcm = AESGCM(key)
    combined = base64.b64decode(ciphertext_b64.encode("utf-8"))
    nonce = combined[:12]
    ciphertext = combined[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


# Token generation
def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token (hex string)."""
    return secrets.token_hex(length)


def hash_token(token: str) -> str:
    """Hash a token using SHA-256 for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    """Verify a token against its SHA-256 hash using constant-time comparison."""
    computed = hash_token(token)
    return hmac.compare_digest(computed, token_hash)


# API key generation
def generate_api_key() -> Tuple[str, str]:
    """
    Generate an API key and its hash.
    Returns (raw_key, hashed_key). Store only the hash.
    """
    raw_key = "iga_" + secrets.token_urlsafe(40)
    hashed = hash_token(raw_key)
    return raw_key, hashed


# Device fingerprint
def generate_device_fingerprint(user_agent: str, ip: str, accept_language: str) -> str:
    """Generate a device fingerprint from request attributes."""
    data = f"{user_agent}|{ip}|{accept_language}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# CSRF token
def generate_csrf_token() -> str:
    """Generate a CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(token: str, session_token: str) -> bool:
    """Verify a CSRF token against the session token using constant-time comparison."""
    if not token or not session_token:
        return False
    return hmac.compare_digest(token, session_token)


# Request signing
def sign_request(payload: dict, secret: str) -> str:
    """Sign a request payload using HMAC-SHA256."""
    sorted_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        secret.encode("utf-8"),
        sorted_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def verify_request_signature(payload: dict, signature: str, secret: str) -> bool:
    """Verify a request signature using constant-time comparison."""
    expected = sign_request(payload, secret)
    return hmac.compare_digest(expected, signature)
