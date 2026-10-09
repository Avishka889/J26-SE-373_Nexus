"""Encryption for provider tokens at rest.

Fernet, from the cryptography package's recipes layer: authenticated symmetric
encryption with the footguns removed. The key is derived from `SECRET_KEY` with
HKDF-SHA256 under a fixed label, so any high entropy string works as the
secret, including a value generated the way `.env.example` suggests, and the
same secret always derives the same key.

An empty secret refuses at the first use rather than at boot: the rest of the
orchestrator runs fine without a secret store, and a server that cannot
encrypt must say so the moment somebody asks it to, not store plaintext.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .errors import DomainError

#: Versioned so a future scheme change can derive a different key from the
#: same secret and re-encrypt, instead of quietly changing what old bytes mean.
_DERIVATION_LABEL = b"sdlc-connections-v1"


class SecretStoreUnavailable(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "SECRET_KEY is not set, so tokens cannot be encrypted at rest. "
            "Set it in .env (see .env.example) and restart.",
            status_code=503,
        )


def _fernet(secret_key: str) -> Fernet:
    if not secret_key.strip():
        raise SecretStoreUnavailable()
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_DERIVATION_LABEL,
    ).derive(secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(secret_key: str, value: str) -> bytes:
    return _fernet(secret_key).encrypt(value.encode())


def decrypt(secret_key: str, token: bytes) -> str:
    """The stored value, or a refusal that names the real problem.

    An InvalidToken here means the ciphertext was written under a different
    SECRET_KEY. Saying "invalid token" would send someone to debug the GitHub
    token; the actual fix is reconnecting the provider so the value is
    re-encrypted under the current key.
    """
    try:
        return _fernet(secret_key).decrypt(token).decode()
    except InvalidToken as error:
        raise DomainError(
            "A stored credential could not be decrypted, which means SECRET_KEY "
            "changed since it was saved. Revoke the connection and connect again.",
            status_code=409,
        ) from error


def redacted(text: str, *secrets: str) -> str:
    """`text` with every known secret value blanked, for error paths.

    Provider errors sometimes echo the credential back (GitHub does not, but
    this code cannot know every provider it will ever talk to). Anything that
    might carry an upstream message into a log or an audit row passes through
    here first.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text
