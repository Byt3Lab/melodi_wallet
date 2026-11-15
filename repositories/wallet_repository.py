from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.wallet_model import (
    WalletModel,
    WalletTransactionModel,
    WalletTransferModel,
    WalletBalanceModel,
    WalletLimitModel,
    WalletSecurityModel,
    WalletBranchConfigModel,
    WalletStatus,
    TransactionStatus,
    TransactionType,
    TransactionDirection,
    TransferStatus,
)


class WalletRepository:


    @staticmethod
    async def get_wallet_by_id(session: AsyncSession, wallet_id: int, lock: bool = False) -> Optional[WalletModel]:
        stmt = select(WalletModel).where(WalletModel.id == wallet_id)
        if lock:
            stmt = stmt.with_for_update()
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_wallets_by_user(session: AsyncSession, user_id: str, branch_id: Optional[str] = None) -> List[WalletModel]:
        stmt = select(WalletModel).where(WalletModel.user_id == str(user_id))
        if branch_id:
            stmt = stmt.where(WalletModel.branch_id == str(branch_id))
        stmt = stmt.order_by(WalletModel.is_default.desc(), WalletModel.id.asc())
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def count_user_wallets(session: AsyncSession, user_id: str) -> int:
        stmt = select(func.count(WalletModel.id)).where(WalletModel.user_id == str(user_id), WalletModel.status != WalletStatus.CLOSED)
        res = await session.execute(stmt)
        return res.scalar() or 0

    @staticmethod
    async def get_default_wallet(session: AsyncSession, user_id: str) -> Optional[WalletModel]:
        stmt = select(WalletModel).where(WalletModel.user_id == str(user_id), WalletModel.is_default == True, WalletModel.status == WalletStatus.ACTIVE)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def create_wallet(
        session: AsyncSession,
        user_id: str,
        country_code: str,
        currency_code: str,
        name: str,
        branch_id: Optional[str] = None,
        is_default: bool = False
    ) -> WalletModel:
        if is_default:
            # Unset default on other wallets of this user
            existing = await WalletRepository.get_wallets_by_user(session, user_id)
            for w in existing:
                if w.is_default:
                    w.is_default = False

        wallet = WalletModel(
            user_id=str(user_id),
            branch_id=branch_id,
            country_code=country_code.upper(),
            currency_code=currency_code.upper(),
            name=name.strip(),
            status=WalletStatus.ACTIVE,
            is_default=is_default
        )

        session.add(wallet)
        await session.flush()

        # Initialize balance and security models
        balance = WalletBalanceModel(wallet_id=wallet.id, available_balance=0.00, pending_balance=0.00)
        security = WalletSecurityModel(wallet_id=wallet.id, pin_hash=None, failed_attempts=0)
        session.add(balance)
        session.add(security)
        await session.flush()
        return wallet

    @staticmethod
    async def get_transaction_by_reference(session: AsyncSession, reference: str) -> Optional[WalletTransactionModel]:
        stmt = select(WalletTransactionModel).where(WalletTransactionModel.reference == reference)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_wallet_transactions(
        session: AsyncSession,
        wallet_id: int,
        type_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[WalletTransactionModel]:
        stmt = select(WalletTransactionModel).where(WalletTransactionModel.wallet_id == wallet_id)
        if type_filter:
            stmt = stmt.where(WalletTransactionModel.type == TransactionType(type_filter))
        if status_filter:
            stmt = stmt.where(WalletTransactionModel.status == TransactionStatus(status_filter))
        stmt = stmt.order_by(WalletTransactionModel.created_at.desc(), WalletTransactionModel.id.desc()).limit(limit).offset(offset)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_daily_sum(
        session: AsyncSession,
        wallet_id: int,
        tx_type: TransactionType,
        target_date: Optional[date] = None
    ) -> Decimal:
        if not target_date:
            target_date = date.today()
        stmt = select(func.coalesce(func.sum(WalletTransactionModel.amount), 0.00)).where(
            WalletTransactionModel.wallet_id == wallet_id,
            WalletTransactionModel.type == tx_type,
            WalletTransactionModel.status == TransactionStatus.COMPLETED,
            func.date(WalletTransactionModel.created_at) == target_date
        )
        res = await session.execute(stmt)
        val = res.scalar() or 0.0
        return Decimal(str(val))

    @staticmethod
    async def get_wallet_limits(session: AsyncSession, country_code: str) -> WalletLimitModel:
        stmt = select(WalletLimitModel).where(WalletLimitModel.country_code == country_code.upper())
        res = await session.execute(stmt)
        limit_obj = res.scalar_one_or_none()
        if not limit_obj:
            # Default fallback limits if country not seeded yet
            limit_obj = WalletLimitModel(
                country_code=country_code.upper(),
                max_wallets_per_user=3,
                daily_transfer_limit=500000.00,
                daily_withdrawal_limit=300000.00,
                daily_payment_limit=1000000.00,
                max_balance=5000000.00
            )
            session.add(limit_obj)
            await session.flush()
        return limit_obj

    @staticmethod
    async def get_all_wallets(
        session: AsyncSession,
        user_id: Optional[str] = None,
        search: Optional[str] = None,
        status: Optional[str] = None,
        branch_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WalletModel]:
        stmt = select(WalletModel)
        if user_id and user_id.lower() != "all":
            stmt = stmt.where(WalletModel.user_id == str(user_id))
        if status and status.lower() != "all":
            try:
                stmt = stmt.where(WalletModel.status == WalletStatus(status))
            except ValueError:
                pass
        if branch_id and branch_id.lower() != "all":
            stmt = stmt.where(WalletModel.branch_id == str(branch_id))
        if search and search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    WalletModel.name.ilike(term),
                    WalletModel.user_id.ilike(term),
                    WalletModel.country_code.ilike(term),
                    WalletModel.currency_code.ilike(term)
                )
            )
        stmt = stmt.order_by(WalletModel.id.desc()).limit(limit).offset(offset)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_global_stats(session: AsyncSession) -> dict:
        stmt_total_wallets = select(func.count(WalletModel.id))
        res_total = await session.execute(stmt_total_wallets)
        total_wallets = res_total.scalar() or 0

        stmt_active_wallets = select(func.count(WalletModel.id)).where(WalletModel.status == WalletStatus.ACTIVE)
        res_active = await session.execute(stmt_active_wallets)
        active_wallets = res_active.scalar() or 0

        stmt_suspended_wallets = select(func.count(WalletModel.id)).where(WalletModel.status == WalletStatus.SUSPENDED)
        res_suspended = await session.execute(stmt_suspended_wallets)
        suspended_wallets = res_suspended.scalar() or 0

        stmt_total_balance = select(func.coalesce(func.sum(WalletBalanceModel.available_balance), 0.00))
        res_balance = await session.execute(stmt_total_balance)
        total_balance = float(res_balance.scalar() or 0.0)

        return {
            "total_wallets": total_wallets,
            "active_wallets": active_wallets,
            "suspended_wallets": suspended_wallets,
            "total_balance": total_balance,
        }

    @staticmethod
    async def get_branch_config(session: AsyncSession, branch_id: str) -> WalletBranchConfigModel:
        stmt = select(WalletBranchConfigModel).where(WalletBranchConfigModel.branch_id == str(branch_id))
        res = await session.execute(stmt)
        config = res.scalar_one_or_none()
        if not config:
            config = WalletBranchConfigModel(
                branch_id=str(branch_id),
                is_enabled=True,
                max_wallets_per_user=1
            )
            session.add(config)
            await session.flush()
        return config

    @staticmethod
    async def get_all_branch_configs(session: AsyncSession) -> List[WalletBranchConfigModel]:
        stmt = select(WalletBranchConfigModel)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def count_user_wallets_in_branch(session: AsyncSession, user_id: str, branch_id: str) -> int:
        stmt = select(func.count(WalletModel.id)).where(
            WalletModel.user_id == str(user_id),
            WalletModel.branch_id == str(branch_id),
            WalletModel.status != WalletStatus.CLOSED
        )
        res = await session.execute(stmt)
        return res.scalar() or 0


