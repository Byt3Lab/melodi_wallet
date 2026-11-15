from decimal import Decimal
from typing import Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ledger_service import LedgerService
from .wallet_balance_service import WalletBalanceService
from .wallet_limit_service import WalletLimitService
from .wallet_security_service import WalletSecurityService
from .wallet_event_publisher import WalletEventPublisher
from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import (
    WalletModel,
    WalletTransactionModel,
    WalletTransferModel,
    TransactionType,
    TransactionDirection,
    TransactionStatus,
    TransferStatus,
    WalletStatus,
)


class TransferService:

    @staticmethod
    async def transfer_funds(
        session: AsyncSession,
        source_wallet_id: int,
        destination_wallet_id: int,
        amount: Decimal,
        pin: Optional[str] = None,
        description: Optional[str] = None,
        created_by: Optional[str] = None,
        module_instance=None
    ) -> Tuple[WalletTransferModel, WalletTransactionModel, WalletTransactionModel]:
        if amount <= Decimal("0.00"):
            raise ValueError(f"Le montant du transfert doit être supérieur à zéro ({amount})")

        if source_wallet_id == destination_wallet_id:
            raise ValueError("Impossible d'effectuer un transfert vers le même portefeuille.")

        # Lock source & destination wallets in deterministic order to prevent deadlock
        first_id, second_id = sorted([source_wallet_id, destination_wallet_id])
        w1 = await WalletRepository.get_wallet_by_id(session, first_id, lock=True)
        w2 = await WalletRepository.get_wallet_by_id(session, second_id, lock=True)

        source_wallet = w1 if w1 and w1.id == source_wallet_id else w2
        dest_wallet = w2 if w2 and w2.id == destination_wallet_id else w1

        if not source_wallet:
            raise ValueError(f"Portefeuille émetteur #{source_wallet_id} introuvable.")
        if not dest_wallet:
            raise ValueError(f"Portefeuille destinataire #{destination_wallet_id} introuvable.")

        if source_wallet.status != WalletStatus.ACTIVE or dest_wallet.status != WalletStatus.ACTIVE:
            raise ValueError("L'un des portefeuilles est suspendu ou inactif.")

        # Currency match check
        if source_wallet.currency_code != dest_wallet.currency_code:
            raise ValueError(f"Incompatibilité de devises : Émetteur en {source_wallet.currency_code}, Destinataire en {dest_wallet.currency_code}.")

        # 1. Verify PIN on source wallet
        await WalletSecurityService.verify_wallet_pin(session, source_wallet.id, pin)

        # 2. Check source available balance
        avail_source, _ = await WalletBalanceService.get_balance(session, source_wallet.id)
        if avail_source < amount:
            raise ValueError(f"Solde insuffisant pour le transfert. Disponible: {avail_source} {source_wallet.currency_code}, Requis: {amount} {source_wallet.currency_code}")

        # 3. Check daily transfer limit on source
        await WalletLimitService.validate_daily_transfer_limit(session, source_wallet, amount)

        # 4. Check max balance limit on destination
        await WalletLimitService.validate_max_balance_limit(session, dest_wallet, amount)

        desc_source = description or f"Transfert vers portefeuille #{dest_wallet.id} ({dest_wallet.name})"
        desc_dest = description or f"Transfert reçu depuis portefeuille #{source_wallet.id} ({source_wallet.name})"

        ref = LedgerService.generate_reference("TRSF")

        # 5. Record Debit Transaction on Source
        tx_debit = await LedgerService.record_transaction(
            session=session,
            wallet_id=source_wallet.id,
            type=TransactionType.TRANSFER_OUT,
            direction=TransactionDirection.DEBIT,
            amount=amount,
            currency_code=source_wallet.currency_code,
            description=desc_source,
            status=TransactionStatus.COMPLETED,
            reference=f"{ref}-OUT",
            created_by=created_by or source_wallet.user_id
        )

        # 6. Record Credit Transaction on Destination
        tx_credit = await LedgerService.record_transaction(
            session=session,
            wallet_id=dest_wallet.id,
            type=TransactionType.TRANSFER_IN,
            direction=TransactionDirection.CREDIT,
            amount=amount,
            currency_code=dest_wallet.currency_code,
            description=desc_dest,
            status=TransactionStatus.COMPLETED,
            reference=f"{ref}-IN",
            created_by=created_by or source_wallet.user_id
        )

        # 7. Record Transfer Relation
        transfer_record = WalletTransferModel(
            source_wallet_id=source_wallet.id,
            destination_wallet_id=dest_wallet.id,
            debit_transaction_id=tx_debit.id,
            credit_transaction_id=tx_credit.id,
            status=TransferStatus.COMPLETED
        )
        session.add(transfer_record)
        await session.flush()

        # 8. Sync Balances
        bal_source = await WalletBalanceService.sync_wallet_balance(session, source_wallet.id)
        bal_dest = await WalletBalanceService.sync_wallet_balance(session, dest_wallet.id)

        # 9. Publish Events
        if module_instance:
            payload_out = {
                "transfer_id": transfer_record.id,
                "source_wallet_id": source_wallet.id,
                "destination_wallet_id": dest_wallet.id,
                "amount": float(amount),
                "currency_code": source_wallet.currency_code,
                "debit_transaction_id": tx_debit.id,
                "user_id": source_wallet.user_id,
                "new_available_balance": float(bal_source.available_balance)
            }
            payload_in = {
                "transfer_id": transfer_record.id,
                "source_wallet_id": source_wallet.id,
                "destination_wallet_id": dest_wallet.id,
                "amount": float(amount),
                "currency_code": dest_wallet.currency_code,
                "credit_transaction_id": tx_credit.id,
                "user_id": dest_wallet.user_id,
                "new_available_balance": float(bal_dest.available_balance)
            }
            await WalletEventPublisher.publish_event(module_instance, "WalletTransferred", payload_out)
            await WalletEventPublisher.publish_event(module_instance, "WalletReceived", payload_in)
            await WalletEventPublisher.publish_event(module_instance, "WalletBalanceUpdated", payload_out)
            await WalletEventPublisher.publish_event(module_instance, "WalletBalanceUpdated", payload_in)

        return transfer_record, tx_debit, tx_credit
