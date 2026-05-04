"""Authentication service for multi-user support."""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from django.db.models import Q

from app.models import AuditLog, FailedLoginAttempt, User, UserSession, UserAPIKey

logger = logging.getLogger(__name__)

# ---------- Password policy ----------
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")

MAX_FAILED_LOGINS = 7
LOCKOUT_MINUTES = 15


def validate_password(password: str) -> tuple[bool, str]:
    if len(password) < _PASSWORD_MIN_LENGTH:
        return False, f"Hasło musi mieć min. {_PASSWORD_MIN_LENGTH} znaków"
    if not _PASSWORD_PATTERN.match(password):
        return False, "Hasło musi zawierać wielką literę, małą literę i cyfrę"
    return True, ""


def _client_ip(ip_address: str | None) -> str:
    return (ip_address or "unknown")[:45]


class AuthService:
    """Handles user authentication and session management."""

    SESSION_DURATION_DAYS = 1

    def register(
        self,
        email: str,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> tuple[bool, str, Optional[User]]:
        """Register a new user."""
        # Validate password strength
        pw_ok, pw_msg = validate_password(password)
        if not pw_ok:
            return False, pw_msg, None

        # Check if email exists
        existing = User.objects.filter(email=email.lower()).first()
        if existing:
            return False, "Email już zarejestrowany", None

        # Check if username exists
        existing = User.objects.filter(username=username.lower()).first()
        if existing:
            return False, "Nazwa użytkownika zajęta", None

        # Create user
        user = User(
            email=email.lower(),
            username=username.lower(),
        )
        user.set_password(password)
        user.save()

        AuditLog(user_id=user.id, action="register", resource="user", ip_address=_client_ip(ip_address)).save()

        return True, "Konto utworzone", user

    def login(
        self,
        email_or_username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> tuple[bool, str, Optional[str]]:
        """Login user and create session. Returns (success, message, token)."""
        ip = _client_ip(ip_address)

        # Find user
        user = User.objects.filter(
            Q(email=email_or_username.lower()) |
            Q(username=email_or_username.lower())
        ).first()

        if not user:
            return False, "Nieprawidłowy email/login lub hasło", None

        if not user.is_active:
            return False, "Konto nieaktywne", None

        # Check lockout
        cutoff = datetime.utcnow() - timedelta(minutes=LOCKOUT_MINUTES)
        recent_failures = FailedLoginAttempt.objects.filter(
            user_id=user.id,
            timestamp__gt=cutoff,
        ).count()
        if recent_failures >= MAX_FAILED_LOGINS:
            logger.warning("Account locked out: user_id=%s ip=%s", user.id, ip)
            return False, f"Zbyt wiele prób logowania. Spróbuj za {LOCKOUT_MINUTES} min.", None

        if not user.check_password(password):
            FailedLoginAttempt(user_id=user.id, ip_address=ip).save()
            return False, "Nieprawidłowy email/login lub hasło", None

        # Successful login – clear failed attempts
        FailedLoginAttempt.objects.filter(user_id=user.id).delete()

        # Update last login
        user.last_login = datetime.utcnow()
        user.save()

        # Create session token
        token = secrets.token_urlsafe(48)
        user_session = UserSession(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(days=self.SESSION_DURATION_DAYS),
            ip_address=ip,
            user_agent=user_agent[:256] if user_agent else None
        )
        user_session.save()
        AuditLog(user_id=user.id, action="login", resource="session", ip_address=ip).save()

        return True, "Zalogowano", token
    
    def validate_token(self, token: str) -> Optional[User]:
        """Validate session token and return user."""
        if not token:
            return None
        
        user_session = UserSession.objects.filter(
            token=token,
            expires_at__gt=datetime.utcnow()
        ).first()
        
        if not user_session:
            return None
        
        return user_session.user
    
    def logout(self, token: str) -> bool:
        """Invalidate session token."""
        user_session = UserSession.objects.filter(token=token).first()
        
        if user_session:
            user_session.delete()
            return True
        return False
    
    def logout_all(self, user_id: int) -> int:
        """Logout from all sessions."""
        count, _ = UserSession.objects.filter(user_id=user_id).delete()
        return count
    
    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions."""
        count, _ = UserSession.objects.filter(expires_at__lt=datetime.utcnow()).delete()
        return count


class APIKeyService:
    """Manages user API keys for exchanges."""

    _OLD_XOR_KEY = "AgentKryptoSecretKey2024!"

    def __init__(self) -> None:
        from cryptography.fernet import Fernet
        key = os.getenv("API_KEY_ENCRYPTION_KEY", "")
        if not key:
            raise RuntimeError(
                "Brak zmiennej środowiskowej API_KEY_ENCRYPTION_KEY. "
                "Wygeneruj: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self._fernet = Fernet(key.encode())

    # ---------- Fernet encryption ----------
    def _encrypt(self, text: str) -> str:
        return self._fernet.encrypt(text.encode()).decode()

    def _decrypt(self, encrypted_text: str) -> str:
        try:
            return self._fernet.decrypt(encrypted_text.encode()).decode()
        except Exception:
            # Fallback: try old XOR decryption for migration
            return self._decrypt_xor_legacy(encrypted_text)

    @staticmethod
    def _decrypt_xor_legacy(encrypted_hex: str) -> str:
        try:
            encrypted = bytes.fromhex(encrypted_hex)
            key = APIKeyService._OLD_XOR_KEY.encode()
            decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
            return decrypted.decode()
        except Exception:
            return ""

    def re_encrypt_from_xor(self) -> int:
        """Migrate all XOR-encrypted secrets to Fernet. Returns count."""
        all_keys = list(UserAPIKey.objects.all())
        migrated = 0
        for k in all_keys:
            plain = self._decrypt_xor_legacy(k.api_secret_encrypted)
            if plain:
                k.api_secret_encrypted = self._encrypt(plain)
                k.save()
                migrated += 1
        if migrated:
            logger.info("Migrated %d API keys from XOR to Fernet", migrated)
        return migrated
    
    def add_api_key(
        self,
        user_id: int,
        label: str,
        api_key: str,
        api_secret: str,
        exchange: str = "binance",
        is_testnet: bool = False,
        permissions: str = "read",
        ip_address: str | None = None,
    ) -> tuple[bool, str, Optional[UserAPIKey]]:
        """Add API key for user."""
        # Check if key already exists
        existing = UserAPIKey.objects.filter(
            user_id=user_id,
            api_key=api_key
        ).first()
        
        if existing:
            return False, "Ten klucz API już istnieje", None
        
        # Encrypt secret
        encrypted_secret = self._encrypt(api_secret)
        
        api_key_obj = UserAPIKey(
            user_id=user_id,
            exchange=exchange,
            label=label,
            api_key=api_key,
            api_secret_encrypted=encrypted_secret,
            is_testnet=is_testnet,
            permissions=permissions
        )
        api_key_obj.save()
        AuditLog(
            user_id=user_id,
            action="api_key_added",
            resource=f"{exchange}:{api_key[:8]}...",
            details=f"testnet={is_testnet} perms={permissions}",
            ip_address=_client_ip(ip_address),
        ).save()
        
        return True, "Klucz API dodany", api_key_obj
    
    def get_user_api_keys(self, user_id: int) -> list[UserAPIKey]:
        """Get all API keys for user."""
        return list(UserAPIKey.objects.filter(
            user_id=user_id,
            is_active=True
        ))
    
    def get_decrypted_secret(self, api_key: UserAPIKey) -> str:
        """Get decrypted API secret."""
        return self._decrypt(api_key.api_secret_encrypted)
    
    def delete_api_key(self, user_id: int, key_id: int) -> bool:
        """Delete API key."""
        api_key = UserAPIKey.objects.filter(
            id=key_id,
            user_id=user_id
        ).first()
        
        if api_key:
            api_key.delete()
            return True
        return False
    
    def toggle_api_key(self, user_id: int, key_id: int) -> bool:
        """Toggle API key active status."""
        api_key = UserAPIKey.objects.filter(
            id=key_id,
            user_id=user_id
        ).first()
        
        if api_key:
            api_key.is_active = not api_key.is_active
            api_key.save()
            return True
        return False
