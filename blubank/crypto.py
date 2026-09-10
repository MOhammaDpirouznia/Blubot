import json
from cryptography.fernet import Fernet
import config

_fernet_instance = None

def get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        key = config.ENCRYPTION_KEY.encode()
        # If key length is not 32 url-safe base64, Fernet will raise an error.
        # Fallback to generate or pad safely for safety.
        try:
            _fernet_instance = Fernet(key)
        except Exception:
            import base64
            padded = base64.urlsafe_b64encode((config.ENCRYPTION_KEY.ljust(32)[:32]).encode())
            _fernet_instance = Fernet(padded)
    return _fernet_instance

def encrypt_session_data(data: dict) -> str:
    """Encrypts a dictionary of session data into an AES-encrypted string."""
    f = get_fernet()
    raw = json.dumps(data).encode("utf-8")
    return f.encrypt(raw).decode("utf-8")

def decrypt_session_data(token_str: str) -> dict:
    """Decrypts an AES-encrypted string back into a dictionary."""
    f = get_fernet()
    decrypted = f.decrypt(token_str.encode("utf-8"))
    return json.loads(decrypted.decode("utf-8"))
