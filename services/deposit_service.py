from decimal import Decimal
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .ledger_service import LedgerService
from .wallet_balance_service import WalletBalanceService
from .wallet_limit_service import WalletLimitService
from .wallet_event_publisher import WalletEventPublisher
from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import WalletTransactionModel, TransactionType, TransactionDirection, TransactionStatus, WalletStatus


class DepositService:

    @staticmethod
    async def deposit_funds(
        session: AsyncSession,
        wallet_id: int,
        amount: Decimal,
        description: Optional[str] = None,
        reference: Optional[str] = None,
        created_by: Optional[str] = None,
        module_instance=None
    ) -> WalletTransactionModel:
        if amount <= Decimal("0.00"):
            raise ValueError(f"Le montant de l'approvisionnement doit être supérieur à zéro ({amount})")

        wallet = await WalletRepository.get_wallet_by_id(session, wallet_id, lock=True)
        if not wallet:
            raise ValueError(f"Portefeuille #{wallet_id} introuvable.")

        if wallet.status != WalletStatus.ACTIVE and str(wallet.status) != "active":
            raise ValueError(f"Le portefeuille est inactif ou suspendu ({wallet.status}). Impossible d'effectuer l'opération.")

        # Validate balance limit
        await WalletLimitService.validate_max_balance_limit(session, wallet, amount)

        desc = description or f"Approvisionnement du portefeuille {wallet.name}"

        # Record Credit Transaction in Ledger
        tx = await LedgerService.record_transaction(
            session=session,
            wallet_id=wallet.id,
            type=TransactionType.DEPOSIT,
            direction=TransactionDirection.CREDIT,
            amount=amount,
            currency_code=wallet.currency_code,
            description=desc,
            status=TransactionStatus.COMPLETED,
            reference=reference,
            created_by=created_by
        )

        # Sync Balance
        bal_record = await WalletBalanceService.sync_wallet_balance(session, wallet.id)

        # Publish Events
        if module_instance:
            payload = {
                "wallet_id": wallet.id,
                "user_id": wallet.user_id,
                "amount": float(amount),
                "currency_code": wallet.currency_code,
                "transaction_id": tx.id,
                "reference": tx.reference,
                "description": desc,
                "new_available_balance": float(bal_record.available_balance)
            }
            await WalletEventPublisher.publish_event(module_instance, "WalletFunded", payload)
            await WalletEventPublisher.publish_event(module_instance, "WalletBalanceUpdated", payload)

        return tx
