# security notes

Rules for this repository:

1. Do not commit `.env`, `*.db`, logs, token files, captured traffic, or browser profiles.
2. Do not hardcode school usernames or passwords in source code.
3. Web login passwords should be stored as Argon2id or bcrypt hashes.
4. School account passwords must be encrypted before storage because automatic login needs decryption.
5. The first production-ready encryption target is Fernet with the encryption key stored outside SQLite, preferably in Windows Credential Manager or another OS key store.
6. Logs must redact token, password, cookie, and session fields.

Current placeholders intentionally do not store plaintext school passwords.

