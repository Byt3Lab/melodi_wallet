from decimal import Decimal
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import WalletModel, TransactionType


class WalletLimitService:

    @staticmethod
    async def validate_wallet_creation_limit(session: AsyncSession, user_id: str, country_code: str):
        count = await WalletRepository.count_user_wallets(session, user_id)
        limits = await WalletRepository.get_wallet_limits(session, country_code)
        if count >= limits.max_wallets_per_user:
            raise ValueError(f"Limite atteinte : Un utilisateur ne peut pas posséder plus de {limits.max_wallets_per_user} portefeuille(s) au {country_code}.")

    @staticmethod
    async def validate_max_balance_limit(session: AsyncSession, wallet: WalletModel, additional_amount: Decimal):
        limits = await WalletRepository.get_wallet_limits(session, wallet.country_code)
        current_available = Decimal(str(wallet.balance_record.available_balance if wallet.balance_record else 0.0))
        future_balance = current_available + additional_amount
        max_bal = Decimal(str(limits.max_balance))
        if future_balance > max_bal:
            raise ValueError(f"Plafond de solde dépassé : Le solde maximal autorisé pour ce portefeuille est de {max_bal} {wallet.currency_code} (Actuel + Ajout: {future_balance})")

    @staticmethod
    async def validate_daily_transfer_limit(session: AsyncSession, wallet: WalletModel, amount: Decimal):
        limits = await WalletRepository.get_wallet_limits(session, wallet.country_code)
        daily_sum = await WalletRepository.get_daily_sum(session, wallet.id, TransactionType.TRANSFER_OUT)
        total_today = daily_sum + amount
        limit = Decimal(str(limits.daily_transfer_limit))
        if total_today > limit:
            raise ValueError(f"Plafond quotidien de transfert dépassé : Limite de {limit} {wallet.currency_code}/jour. (Cumul aujourd'hui + demande: {total_today})")

    @staticmethod
    async def validate_daily_withdrawal_limit(session: AsyncSession, wallet: WalletModel, amount: Decimal):
        limits = await WalletRepository.get_wallet_limits(session, wallet.country_code)
        daily_sum = await WalletRepository.get_daily_sum(session, wallet.id, TransactionType.WITHDRAWAL)
        total_today = daily_sum + amount
        limit = Decimal(str(limits.daily_withdrawal_limit))
        if total_today > limit:
            raise ValueError(f"Plafond quotidien de retrait dépassé : Limite de {limit} {wallet.currency_code}/jour. (Cumul aujourd'hui + demande: {total_today})")

    @staticmethod
    async def validate_daily_payment_limit(session: AsyncSession, wallet: WalletModel, amount: Decimal):
        limits = await WalletRepository.get_wallet_limits(session, wallet.country_code)
        daily_sum = await WalletRepository.get_daily_sum(session, wallet.id, TransactionType.INVOICE_PAYMENT)
        total_today = daily_sum + amount
        limit = Decimal(str(limits.daily_payment_limit))
        if total_today > limit:
            raise ValueError(f"Plafond quotidien de paiement dépassé : Limite de {limit} {wallet.currency_code}/jour. (Cumul aujourd'hui + demande: {total_today})")

    @staticmethod
    async def validate_branch_wallet_limit(session: AsyncSession, user_id: str, branch_id: str):
        if not branch_id or not str(branch_id).strip():
            raise ValueError("Une agence d'attachement (branch_id) est obligatoirement requise pour créer un portefeuille.")

        try:
            from modules.melodi_branches.models.branch_model import BranchModel
            branch = await session.get(BranchModel, str(branch_id))
            if not branch:
                raise ValueError(f"L'agence spécifiée #{branch_id} est introuvable en base de données.")
            if hasattr(branch, "is_active") and not branch.is_active:
                raise ValueError(f"L'agence '{branch.name}' est inactive.")
        except Exception as e:
            if "introuvable" in str(e) or "inactive" in str(e) or "obligatoirement" in str(e):
                raise
            print(f"Notice validating branch: {e}")

        config = await WalletRepository.get_branch_config(session, str(branch_id))
        if not config.is_enabled:
            raise ValueError(f"L'agence #{branch_id} n'est pas autorisée à héberger des comptes portefeuilles numériques.")

        count = await WalletRepository.count_user_wallets_in_branch(session, user_id, str(branch_id))
        if count >= config.max_wallets_per_user:
            raise ValueError(f"Limite d'agence atteinte : Cet utilisateur possède déjà {count} portefeuille(s) dans cette agence (Limite autorisée : {config.max_wallets_per_user}).")

