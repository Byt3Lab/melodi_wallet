import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.wallet_model import (
    WalletModel,
    WalletTransactionModel,
    WalletBalanceModel,
    TransactionType,
    TransactionDirection,
    TransactionStatus,
)


class LedgerService:
    """
    Le Ledger (Grand Livre) est la source unique de vérité absolue.
    Aucune opération ne modifie directement un solde sans générer une écriture comptable.
    """

    @staticmethod
    def generate_reference(prefix: str = "TX") -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        uid = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{timestamp}-{uid}"

    @staticmethod
    async def calculate_ledger_balance(session: AsyncSession, wallet_id: int) -> Tuple[Decimal, Decimal]:
        """
        Calcule le solde réel à partir du solde cumulé des transactions COMPLETED :
        Solde disponible = SUM(credit) - SUM(debit) des transactions COMPLETED.
        Solde en attente = SUM(credit) - SUM(debit) des transactions PENDING.
        """
        # Sum credits completed
        stmt_credit = select(func.coalesce(func.sum(WalletTransactionModel.amount), 0.00)).where(
            WalletTransactionModel.wallet_id == wallet_id,
            WalletTransactionModel.direction == TransactionDirection.CREDIT,
            WalletTransactionModel.status == TransactionStatus.COMPLETED
        )
        res_credit = await session.execute(stmt_credit)
        total_credit = Decimal(str(res_credit.scalar() or 0.0))

        # Sum debits completed
        stmt_debit = select(func.coalesce(func.sum(WalletTransactionModel.amount), 0.00)).where(
            WalletTransactionModel.wallet_id == wallet_id,
            WalletTransactionModel.direction == TransactionDirection.DEBIT,
            WalletTransactionModel.status == TransactionStatus.COMPLETED
        )
        res_debit = await session.execute(stmt_debit)
        total_debit = Decimal(str(res_debit.scalar() or 0.0))

        available_balance = total_credit - total_debit

        # Sum pending
        stmt_pending = select(func.coalesce(func.sum(WalletTransactionModel.amount), 0.00)).where(
            WalletTransactionModel.wallet_id == wallet_id,
            WalletTransactionModel.status == TransactionStatus.PENDING
        )
        res_pending = await session.execute(stmt_pending)
        pending_balance = Decimal(str(res_pending.scalar() or 0.0))

        return available_balance, pending_balance

    @staticmethod
    async def record_transaction(
        session: AsyncSession,
        wallet_id: int,
        type: TransactionType,
        direction: TransactionDirection,
        amount: Decimal,
        currency_code: str,
        description: str,
        status: TransactionStatus = TransactionStatus.COMPLETED,
        reference: Optional[str] = None,
        created_by: Optional[str] = None
    ) -> WalletTransactionModel:
        if amount <= Decimal("0.00"):
            raise ValueError(f"Le montant de la transaction doit être supérieur à zéro ({amount})")

        ref = reference or LedgerService.generate_reference(type.value.upper()[:4])

        tx = WalletTransactionModel(
            wallet_id=wallet_id,
            type=type,
            direction=direction,
            amount=float(amount),
            currency_code=currency_code.upper(),
            status=status,
            reference=ref,
            description=description,
            created_by=created_by,
            created_at=datetime.utcnow()
        )
        session.add(tx)
        await session.flush()
        return tx
