"""Authentication service for multi-user support."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserSession, UserAPIKey


class AuthService:
    """Handles user authentication and session management."""
    
    SESSION_DURATION_DAYS = 30
    
    def register(
        self,
        session: Session,
        email: str,
        username: str,
        password: str
    ) -> tuple[bool, str, Optional[User]]:
        """Register a new user."""
        # Check if email exists
        existing = session.execute(
            select(User).where(User.email == email.lower())
        ).scalar_one_or_none()
        if existing:
            return False, "Email już zarejestrowany", None
        
        # Check if username exists
        existing = session.execute(
            select(User).where(User.username == username.lower())
        ).scalar_one_or_none()
        if existing:
            return False, "Nazwa użytkownika zajęta", None
        
        # Create user
        user = User(
            email=email.lower(),
            username=username.lower(),
        )
        user.set_password(password)
        session.add(user)
        session.commit()
        
        return True, "Konto utworzone", user
    
    def login(
        self,
        session: Session,
        email_or_username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> tuple[bool, str, Optional[str]]:
        """Login user and create session. Returns (success, message, token)."""
        # Find user
        user = session.execute(
            select(User).where(
                (User.email == email_or_username.lower()) | 
                (User.username == email_or_username.lower())
            )
        ).scalar_one_or_none()
        
        if not user:
            return False, "Nieprawidłowy email/login lub hasło", None
        
        if not user.is_active:
            return False, "Konto nieaktywne", None
        
        if not user.check_password(password):
            return False, "Nieprawidłowy email/login lub hasło", None
        
        # Update last login
        user.last_login = datetime.utcnow()
        
        # Create session token
        token = secrets.token_urlsafe(48)
        user_session = UserSession(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(days=self.SESSION_DURATION_DAYS),
            ip_address=ip_address,
            user_agent=user_agent[:256] if user_agent else None
        )
        session.add(user_session)
        session.commit()
        
        return True, "Zalogowano", token
    
    def validate_token(self, session: Session, token: str) -> Optional[User]:
        """Validate session token and return user."""
        if not token:
            return None
        
        user_session = session.execute(
            select(UserSession).where(
                UserSession.token == token,
                UserSession.expires_at > datetime.utcnow()
            )
        ).scalar_one_or_none()
        
        if not user_session:
            return None
        
        return user_session.user
    
    def logout(self, session: Session, token: str) -> bool:
        """Invalidate session token."""
        user_session = session.execute(
            select(UserSession).where(UserSession.token == token)
        ).scalar_one_or_none()
        
        if user_session:
            session.delete(user_session)
            session.commit()
            return True
        return False
    
    def logout_all(self, session: Session, user_id: int) -> int:
        """Logout from all sessions."""
        sessions = session.execute(
            select(UserSession).where(UserSession.user_id == user_id)
        ).scalars().all()
        
        count = len(sessions)
        for s in sessions:
            session.delete(s)
        session.commit()
        return count
    
    def cleanup_expired_sessions(self, session: Session) -> int:
        """Remove expired sessions."""
        expired = session.execute(
            select(UserSession).where(UserSession.expires_at < datetime.utcnow())
        ).scalars().all()
        
        count = len(expired)
        for s in expired:
            session.delete(s)
        session.commit()
        return count


class APIKeyService:
    """Manages user API keys for exchanges."""
    
    # Simple XOR encryption for API secrets (in production use proper encryption)
    ENCRYPTION_KEY = "AgentKryptoSecretKey2024!"
    
    def _encrypt(self, text: str) -> str:
        """Simple encryption for API secrets."""
        key = self.ENCRYPTION_KEY
        encrypted = []
        for i, char in enumerate(text):
            encrypted.append(chr(ord(char) ^ ord(key[i % len(key)])))
        return ''.join(encrypted).encode('latin-1').hex()
    
    def _decrypt(self, encrypted_hex: str) -> str:
        """Decrypt API secret."""
        try:
            encrypted = bytes.fromhex(encrypted_hex).decode('latin-1')
            key = self.ENCRYPTION_KEY
            decrypted = []
            for i, char in enumerate(encrypted):
                decrypted.append(chr(ord(char) ^ ord(key[i % len(key)])))
            return ''.join(decrypted)
        except Exception:
            return ""
    
    def add_api_key(
        self,
        session: Session,
        user_id: int,
        label: str,
        api_key: str,
        api_secret: str,
        exchange: str = "binance",
        is_testnet: bool = False,
        permissions: str = "read"
    ) -> tuple[bool, str, Optional[UserAPIKey]]:
        """Add API key for user."""
        # Check if key already exists
        existing = session.execute(
            select(UserAPIKey).where(
                UserAPIKey.user_id == user_id,
                UserAPIKey.api_key == api_key
            )
        ).scalar_one_or_none()
        
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
        session.add(api_key_obj)
        session.commit()
        
        return True, "Klucz API dodany", api_key_obj
    
    def get_user_api_keys(self, session: Session, user_id: int) -> list[UserAPIKey]:
        """Get all API keys for user."""
        return session.execute(
            select(UserAPIKey).where(
                UserAPIKey.user_id == user_id,
                UserAPIKey.is_active == True
            )
        ).scalars().all()
    
    def get_decrypted_secret(self, api_key: UserAPIKey) -> str:
        """Get decrypted API secret."""
        return self._decrypt(api_key.api_secret_encrypted)
    
    def delete_api_key(self, session: Session, user_id: int, key_id: int) -> bool:
        """Delete API key."""
        api_key = session.execute(
            select(UserAPIKey).where(
                UserAPIKey.id == key_id,
                UserAPIKey.user_id == user_id
            )
        ).scalar_one_or_none()
        
        if api_key:
            session.delete(api_key)
            session.commit()
            return True
        return False
    
    def toggle_api_key(self, session: Session, user_id: int, key_id: int) -> bool:
        """Toggle API key active status."""
        api_key = session.execute(
            select(UserAPIKey).where(
                UserAPIKey.id == key_id,
                UserAPIKey.user_id == user_id
            )
        ).scalar_one_or_none()
        
        if api_key:
            api_key.is_active = not api_key.is_active
            session.commit()
            return True
        return False
