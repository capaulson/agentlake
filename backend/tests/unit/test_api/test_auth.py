"""Tests for authentication and authorization."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from agentlake.core.auth import (
    Role,
    create_jwt_token,
    decode_jwt_token,
    hash_api_key,
    verify_api_key,
)
from agentlake.core.exceptions import AuthorizationError


class TestApiKeyHashing:
    """Tests for API key hashing and verification."""

    def test_hash_is_deterministic(self) -> None:
        key = "test-api-key-123"
        salt = "my-salt"
        h1 = hash_api_key(key, salt)
        h2 = hash_api_key(key, salt)
        assert h1 == h2

    def test_different_keys_produce_different_hashes(self) -> None:
        salt = "my-salt"
        h1 = hash_api_key("key-a", salt)
        h2 = hash_api_key("key-b", salt)
        assert h1 != h2

    def test_different_salts_produce_different_hashes(self) -> None:
        key = "same-key"
        h1 = hash_api_key(key, "salt-a")
        h2 = hash_api_key(key, "salt-b")
        assert h1 != h2

    def test_hash_length(self) -> None:
        h = hash_api_key("test", "salt")
        assert len(h) == 64  # SHA-256 hex digest

    def test_verify_correct_key(self) -> None:
        key = "my-secret-key"
        salt = "test-salt"
        hashed = hash_api_key(key, salt)
        assert verify_api_key(key, hashed, salt) is True

    def test_verify_wrong_key(self) -> None:
        salt = "test-salt"
        hashed = hash_api_key("correct-key", salt)
        assert verify_api_key("wrong-key", hashed, salt) is False

    def test_verify_wrong_salt(self) -> None:
        key = "my-key"
        hashed = hash_api_key(key, "salt-a")
        assert verify_api_key(key, hashed, "salt-b") is False


class TestJWTTokens:
    """Tests for JWT token creation and decoding."""

    def test_create_and_decode(self) -> None:
        secret = "test-secret-key"
        data = {"sub": "user123", "role": "admin"}
        token = create_jwt_token(data, secret)
        decoded = decode_jwt_token(token, secret)
        assert decoded["sub"] == "user123"
        assert decoded["role"] == "admin"

    def test_token_has_expiry(self) -> None:
        secret = "test-secret"
        data = {"sub": "user"}
        token = create_jwt_token(data, secret, expires_hours=24)
        decoded = decode_jwt_token(token, secret)
        assert "exp" in decoded
        assert "iat" in decoded

    def test_invalid_token_raises(self) -> None:
        with pytest.raises(AuthorizationError, match="Invalid or expired"):
            decode_jwt_token("not.a.valid.token", "secret")

    def test_wrong_secret_raises(self) -> None:
        token = create_jwt_token({"sub": "user"}, "secret-a")
        with pytest.raises(AuthorizationError, match="Invalid or expired"):
            decode_jwt_token(token, "secret-b")


class TestRoles:
    """Tests for the Role enum."""

    def test_role_values(self) -> None:
        assert Role.ADMIN.value == "admin"
        assert Role.EDITOR.value == "editor"
        assert Role.VIEWER.value == "viewer"
        assert Role.AGENT.value == "agent"

    def test_role_is_string_enum(self) -> None:
        assert isinstance(Role.ADMIN, str)
        assert Role.ADMIN == "admin"
