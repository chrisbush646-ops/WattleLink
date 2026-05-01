"""
Custom Django password hasher backed by passlib's pbkdf2_sha512.

passlib 1.7.x + bcrypt 5.0 are incompatible (upstream issue), so we use
pbkdf2_sha512, which passlib handles natively without the bcrypt dependency.
pbkdf2_sha512 with 500k rounds is compliant with Australian Privacy Act
requirements for password storage.
"""

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.translation import gettext_lazy as _
from passlib.hash import pbkdf2_sha512


class PasslibPBKDF2Hasher(BasePasswordHasher):
    """
    Passlib-backed PBKDF2-SHA512 hasher.
    Stored format: passlib_pbkdf2_sha512$$<passlib-hash>
    """

    algorithm = "passlib_pbkdf2_sha512"

    def salt(self):
        return ""  # passlib generates salt internally

    def encode(self, password, salt):
        hashed = pbkdf2_sha512.using(rounds=500_000).hash(password)
        return f"{self.algorithm}$${hashed}"

    def decode(self, encoded):
        _, _, phash = encoded.split("$", 2)
        return {"algorithm": self.algorithm, "hash": phash}

    def verify(self, password, encoded):
        decoded = self.decode(encoded)
        return pbkdf2_sha512.verify(password, decoded["hash"])

    def safe_summary(self, encoded):
        decoded = self.decode(encoded)
        return {
            _("algorithm"): self.algorithm,
            _("hash"): mask_hash(decoded["hash"]),
        }

    def must_update(self, encoded):
        decoded = self.decode(encoded)
        return pbkdf2_sha512.needs_update(decoded["hash"])

    def harden_runtime(self, password, encoded):
        pass
