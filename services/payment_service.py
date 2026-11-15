from decimal import Decimal
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession

from .ledger_service import LedgerService
from .wallet_balance_service import WalletBalanceService
from .wallet_limit_service import WalletLimitService
from .wallet_security_service import WalletSecurityService
from .wallet_event_publisher import WalletEventPublisher
from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import WalletTransactionModel, TransactionType, TransactionDirection, TransactionStatus, WalletStatus


class PaymentService:

    @staticmethod
    async def pay_invoice(
        session: AsyncSession,
        wallet_id: int,
        invoice_id: Any,
        amount: Decimal,
        pin: Optional[str] = None,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        module_instance=None
    ) -> WalletTransactionModel:
        if amount <= Decimal("0.00"):
            raise ValueError(f"Le montant du paiement doit être supérieur à zéro ({amount})")

        wallet = await WalletRepository.get_wallet_by_id(session, wallet_id, lock=True)
        if not wallet:
            raise ValueError(f"Portefeuille #{wallet_id} introuvable.")

        if wallet.status != WalletStatus.ACTIVE:
            raise ValueError(f"Le portefeuille est inactif ou suspendu ({wallet.status}).")

        desc = description or f"Règlement de la facture #{invoice_id}"

        try:
            # 1. Verify PIN
            await WalletSecurityService.verify_wallet_pin(session, wallet.id, pin)

            # 2. Check available balance
            avail, _ = await WalletBalanceService.get_balance(session, wallet.id)
            if avail < amount:
                raise ValueError(f"Solde insuffisant pour régler cette facture. Disponible: {avail} {wallet.currency_code}, Facture: {amount} {wallet.currency_code}")

            # 3. Check daily payment limit
            await WalletLimitService.validate_daily_payment_limit(session, wallet, amount)

            # 4. Record Debit Transaction in Ledger
            tx = await LedgerService.record_transaction(
                session=session,
                wallet_id=wallet.id,
                type=TransactionType.INVOICE_PAYMENT,
                direction=TransactionDirection.DEBIT,
                amount=amount,
                currency_code=wallet.currency_code,
                description=desc,
                status=TransactionStatus.COMPLETED,
                reference=LedgerService.generate_reference("INV"),
                created_by=created_by or wallet.user_id
            )

            # 5. Sync Balance
            bal_record = await WalletBalanceService.sync_wallet_balance(session, wallet.id)

            # 6. Publish Event Success
            if module_instance:
                payload = {
                    "wallet_id": wallet.id,
                    "user_id": wallet.user_id,
                    "invoice_id": invoice_id,
                    "amount": float(amount),
                    "currency_code": wallet.currency_code,
                    "transaction_id": tx.id,
                    "reference": tx.reference,
                    "new_available_balance": float(bal_record.available_balance)
                }
                await WalletEventPublisher.publish_event(module_instance, "WalletPaymentCompleted", payload)
                await WalletEventPublisher.publish_event(module_instance, "WalletBalanceUpdated", payload)

            return tx

        except Exception as e:
            if module_instance:
                payload = {
                    "wallet_id": wallet.id,
                    "user_id": wallet.user_id,
                    "invoice_id": invoice_id,
                    "amount": float(amount),
                    "error_message": str(e)
                }
                await WalletEventPublisher.publish_event(module_instance, "WalletPaymentFailed", payload)
            raise e
