import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.wallet_model import WalletSecurityModel, WalletModel, WalletStatus


class WalletSecurityService:

    @staticmethod
    def _hash_pin(pin: str, salt: Optional[str] = None) -> str:
        if not salt:
            salt = os.urandom(16).hex()
        hash_obj = hashlib.sha256((salt + str(pin)).encode("utf-8")).hexdigest()
        return f"{salt}${hash_obj}"

    @staticmethod
    def _verify_pin_hash(pin: str, stored_hash: str) -> bool:
        if not stored_hash or "$" not in stored_hash:
            return False
        salt, expected_hash = stored_hash.split("$", 1)
        computed_hash = hashlib.sha256((salt + str(pin)).encode("utf-8")).hexdigest()
        return computed_hash == expected_hash

    @staticmethod
    async def set_wallet_pin(session: AsyncSession, wallet_id: int, pin: str) -> WalletSecurityModel:
        if not pin or len(str(pin).strip()) < 4:
            raise ValueError("Le code PIN doit comporter au moins 4 chiffres.")

        stmt = select(WalletSecurityModel).where(WalletSecurityModel.wallet_id == wallet_id)
        res = await session.execute(stmt)
        sec = res.scalar_one_or_none()

        pin_hash = WalletSecurityService._hash_pin(str(pin).strip())
        if not sec:
            sec = WalletSecurityModel(wallet_id=wallet_id, pin_hash=pin_hash, failed_attempts=0, locked_until=None)
            session.add(sec)
        else:
            sec.pin_hash = pin_hash
            sec.failed_attempts = 0
            sec.locked_until = None

        await session.flush()
        return sec

    @staticmethod
    async def verify_wallet_pin(session: AsyncSession, wallet_id: int, pin: Optional[str]):
        stmt = select(WalletSecurityModel).where(WalletSecurityModel.wallet_id == wallet_id)
        res = await session.execute(stmt)
        sec = res.scalar_one_or_none()

        if not sec or not sec.pin_hash:
            # PIN not set yet, bypass if PIN verification optional or raise
            return True

        now = datetime.utcnow()
        if sec.locked_until and sec.locked_until > now:
            minutes_left = int((sec.locked_until - now).total_seconds() / 60) + 1
            raise ValueError(f"Portefeuille verrouillé pour raisons de sécurité. Réessayez dans {minutes_left} minute(s).")

        if not pin or not WalletSecurityService._verify_pin_hash(str(pin).strip(), sec.pin_hash):
            sec.failed_attempts += 1
            if sec.failed_attempts >= 3:
                sec.locked_until = now + timedelta(minutes=15)
                sec.failed_attempts = 0
                await session.flush()
                raise ValueError("Code PIN incorrect. 3 tentatives échouées : Le portefeuille est verrouillé pendant 15 minutes.")
            await session.flush()
            remaining = 3 - sec.failed_attempts
            raise ValueError(f"Code PIN incorrect. Il vous reste {remaining} tentative(s) avant verrouillage.")

        # Success
        sec.failed_attempts = 0
        sec.locked_until = None
        await session.flush()
        return True
