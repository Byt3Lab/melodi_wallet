from datetime import datetime
from decimal import Decimal
from typing import Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ledger_service import LedgerService
from ..models.wallet_model import WalletBalanceModel, WalletModel


class WalletBalanceService:

    @staticmethod
    async def sync_wallet_balance(session: AsyncSession, wallet_id: int) -> WalletBalanceModel:
        """
        Recalcule le solde depuis le ledger transactionnel et met à jour la table d'optimisation WalletBalanceModel.
        """
        available_balance, pending_balance = await LedgerService.calculate_ledger_balance(session, wallet_id)

        stmt = select(WalletBalanceModel).where(WalletBalanceModel.wallet_id == wallet_id)
        res = await session.execute(stmt)
        bal_record = res.scalar_one_or_none()

        if not bal_record:
            bal_record = WalletBalanceModel(
                wallet_id=wallet_id,
                available_balance=float(available_balance),
                pending_balance=float(pending_balance),
                updated_at=datetime.utcnow()
            )
            session.add(bal_record)
        else:
            bal_record.available_balance = float(available_balance)
            bal_record.pending_balance = float(pending_balance)
            bal_record.updated_at = datetime.utcnow()

        await session.flush()
        return bal_record

    @staticmethod
    async def get_balance(session: AsyncSession, wallet_id: int) -> Tuple[Decimal, Decimal]:
        """
        Renvoie (available_balance, pending_balance) pour un portefeuille.
        """
        stmt = select(WalletBalanceModel).where(WalletBalanceModel.wallet_id == wallet_id)
        res = await session.execute(stmt)
        bal = res.scalar_one_or_none()

        if not bal:
            bal = await WalletBalanceService.sync_wallet_balance(session, wallet_id)

        return Decimal(str(bal.available_balance)), Decimal(str(bal.pending_balance))
