def hash_web_password(_password: str) -> str:
    raise NotImplementedError("TODO: implement Argon2id or bcrypt password hashing")


def verify_web_password(_password: str, _password_hash: str) -> bool:
    raise NotImplementedError("TODO: implement web password verification")


def encrypt_school_password(_plain_password: str) -> tuple[str, str]:
    raise NotImplementedError("TODO: implement Fernet + OS keyring encryption")


def decrypt_school_password(_encrypted_password: str, _key_id: str) -> str:
    raise NotImplementedError("TODO: implement Fernet + OS keyring decryption")

