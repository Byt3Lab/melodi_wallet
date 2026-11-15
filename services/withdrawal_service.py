from decimal import Decimal
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ledger_service import LedgerService
from .wallet_balance_service import WalletBalanceService
from .wallet_limit_service import WalletLimitService
from .wallet_security_service import WalletSecurityService
from .wallet_event_publisher import WalletEventPublisher
from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import WalletTransactionModel, TransactionType, TransactionDirection, TransactionStatus, WalletStatus


class WithdrawalService:

    @staticmethod
    async def request_withdrawal(
        session: AsyncSession,
        wallet_id: int,
        amount: Decimal,
        pin: Optional[str] = None,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        module_instance=None
    ) -> WalletTransactionModel:
        if amount <= Decimal("0.00"):
            raise ValueError(f"Le montant du retrait doit être supérieur à zéro ({amount})")

        wallet = await WalletRepository.get_wallet_by_id(session, wallet_id, lock=True)
        if not wallet:
            raise ValueError(f"Portefeuille #{wallet_id} introuvable.")

        if wallet.status != WalletStatus.ACTIVE and str(wallet.status) != "active":
            raise ValueError(f"Le portefeuille est inactif ou suspendu ({wallet.status}).")

        # 1. Verify PIN
        await WalletSecurityService.verify_wallet_pin(session, wallet.id, pin)

        # 2. Verify Available Balance
        avail, _ = await WalletBalanceService.get_balance(session, wallet.id)
        if avail < amount:
            raise ValueError(f"Solde insuffisant pour ce retrait. Solde disponible: {avail} {wallet.currency_code}, Demande: {amount} {wallet.currency_code}")

        # 3. Verify Daily Withdrawal Limit
        await WalletLimitService.validate_daily_withdrawal_limit(session, wallet, amount)

        desc = description or f"Demande de retrait du portefeuille {wallet.name}"

        # Record Debit Transaction with status PENDING
        tx = await LedgerService.record_transaction(
            session=session,
            wallet_id=wallet.id,
            type=TransactionType.WITHDRAWAL,
            direction=TransactionDirection.DEBIT,
            amount=amount,
            currency_code=wallet.currency_code,
            description=desc,
            status=TransactionStatus.PENDING,
            created_by=created_by
        )

        await WalletBalanceService.sync_wallet_balance(session, wallet.id)
        return tx

    @staticmethod
    async def confirm_withdrawal(
        session: AsyncSession,
        transaction_id: int,
        approve: bool = True,
        module_instance=None
    ) -> WalletTransactionModel:
        stmt = select(WalletTransactionModel).where(WalletTransactionModel.id == transaction_id).with_for_update()
        res = await session.execute(stmt)
        tx = res.scalar_one_or_none()

        if not tx:
            raise ValueError(f"Transaction de retrait #{transaction_id} introuvable.")

        if tx.type != TransactionType.WITHDRAWAL or tx.status != TransactionStatus.PENDING:
            raise ValueError(f"La transaction #{transaction_id} n'est pas un retrait en attente (Type: {tx.type}, Statut: {tx.status}).")

        wallet = await WalletRepository.get_wallet_by_id(session, tx.wallet_id, lock=True)

        if approve:
            # Re-check available balance before final approval
            avail, _ = await WalletBalanceService.get_balance(session, wallet.id)
            amt = Decimal(str(tx.amount))
            if avail < amt:
                tx.status = TransactionStatus.FAILED
                await session.flush()
                await WalletBalanceService.sync_wallet_balance(session, wallet.id)
                raise ValueError(f"Échec de la confirmation : Solde insuffisant ({avail} < {amt})")

            tx.status = TransactionStatus.COMPLETED
            bal_record = await WalletBalanceService.sync_wallet_balance(session, wallet.id)

            if module_instance:
                payload = {
                    "wallet_id": wallet.id,
                    "user_id": wallet.user_id,
                    "amount": float(tx.amount),
                    "currency_code": wallet.currency_code,
                    "transaction_id": tx.id,
                    "reference": tx.reference,
                    "description": tx.description,
                    "new_available_balance": float(bal_record.available_balance)
                }
                await WalletEventPublisher.publish_event(module_instance, "WalletWithdrawn", payload)
                await WalletEventPublisher.publish_event(module_instance, "WalletBalanceUpdated", payload)
        else:
            tx.status = TransactionStatus.CANCELLED
            await WalletBalanceService.sync_wallet_balance(session, wallet.id)

        await session.flush()
        return tx
