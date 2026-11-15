import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column,
    String as SAString,
    Integer as SAInteger,
    Boolean as SABoolean,
    Enum as SAEnum,
    ForeignKey as SAFK,
    Index,
    Numeric as SANumeric,
    DateTime as SADateTime,
    Text as SAText,
)

from core.orm.model import (
    BaseModel,
    Mapped,
    mapped_column,
    relationship,
    Integer,
    String,
    Boolean,
    Numeric,
    Enum,
    ForeignKey,
)

from ..config import WalletTables


class WalletStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    INVOICE_PAYMENT = "invoice_payment"
    INVOICE_REFUND = "invoice_refund"
    ADJUSTMENT = "adjustment"
    FEE = "fee"


class TransactionDirection(str, enum.Enum):
    CREDIT = "credit"
    DEBIT = "debit"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransferStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class WalletModel(BaseModel):
    __tablename__ = WalletTables.WALLETS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    branch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    country_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


    status: Mapped[WalletStatus] = mapped_column(
        Enum(WalletStatus, native_enum=False),
        default=WalletStatus.ACTIVE,
        nullable=False,
        index=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    transactions: Mapped[List["WalletTransactionModel"]] = relationship(
        "WalletTransactionModel",
        back_populates="wallet",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    balance_record: Mapped[Optional["WalletBalanceModel"]] = relationship(
        "WalletBalanceModel",
        back_populates="wallet",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    security_record: Mapped[Optional["WalletSecurityModel"]] = relationship(
        "WalletSecurityModel",
        back_populates="wallet",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (
        Index("idx_wallet_user_country", "user_id", "country_code"),
    )

    @property
    def available_balance(self) -> float:
        if hasattr(self, "__dict__") and "balance_record" in self.__dict__ and self.balance_record:
            return float(self.balance_record.available_balance) if self.balance_record.available_balance is not None else 0.0
        return 0.0

    @property
    def pending_balance(self) -> float:
        if hasattr(self, "__dict__") and "balance_record" in self.__dict__ and self.balance_record:
            return float(self.balance_record.pending_balance) if self.balance_record.pending_balance is not None else 0.0
        return 0.0

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "branch_id": self.branch_id,
            "country_code": self.country_code,
            "currency_code": self.currency_code,
            "name": self.name,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "available_balance": self.available_balance,
            "pending_balance": self.pending_balance,
        }
        return data


class WalletTransactionModel(BaseModel):
    __tablename__ = WalletTables.TRANSACTIONS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.WALLETS}.id"), nullable=False, index=True)
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False),
        nullable=False,
        index=True
    )
    direction: Mapped[TransactionDirection] = mapped_column(
        Enum(TransactionDirection, native_enum=False),
        nullable=False,
        index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, native_enum=False),
        default=TransactionStatus.PENDING,
        nullable=False,
        index=True
    )
    reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    wallet: Mapped["WalletModel"] = relationship("WalletModel", back_populates="transactions", lazy="selectin")

    __table_args__ = (
        Index("idx_tx_wallet_created", "wallet_id", "created_at"),
        Index("idx_tx_wallet_status", "wallet_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "wallet_id": self.wallet_id,
            "type": self.type.value if hasattr(self.type, "value") else str(self.type),
            "direction": self.direction.value if hasattr(self.direction, "value") else str(self.direction),
            "amount": float(self.amount) if self.amount is not None else 0.0,
            "currency_code": self.currency_code,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "reference": self.reference,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WalletTransferModel(BaseModel):
    __tablename__ = WalletTables.TRANSFERS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.WALLETS}.id"), nullable=False, index=True)
    destination_wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.WALLETS}.id"), nullable=False, index=True)
    debit_transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.TRANSACTIONS}.id"), nullable=False)
    credit_transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.TRANSACTIONS}.id"), nullable=False)
    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus, native_enum=False),
        default=TransferStatus.COMPLETED,
        nullable=False
    )



    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False)

    source_wallet: Mapped["WalletModel"] = relationship("WalletModel", foreign_keys=[source_wallet_id], lazy="selectin")
    destination_wallet: Mapped["WalletModel"] = relationship("WalletModel", foreign_keys=[destination_wallet_id], lazy="selectin")
    debit_transaction: Mapped["WalletTransactionModel"] = relationship("WalletTransactionModel", foreign_keys=[debit_transaction_id], lazy="selectin")
    credit_transaction: Mapped["WalletTransactionModel"] = relationship("WalletTransactionModel", foreign_keys=[credit_transaction_id], lazy="selectin")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_wallet_id": self.source_wallet_id,
            "destination_wallet_id": self.destination_wallet_id,
            "debit_transaction_id": self.debit_transaction_id,
            "credit_transaction_id": self.credit_transaction_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class WalletBalanceModel(BaseModel):
    __tablename__ = WalletTables.BALANCES

    wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.WALLETS}.id"), primary_key=True)
    available_balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0.00, nullable=False)
    pending_balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0.00, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    wallet: Mapped["WalletModel"] = relationship("WalletModel", back_populates="balance_record", lazy="selectin")

    def to_dict(self) -> dict:
        return {
            "wallet_id": self.wallet_id,
            "available_balance": float(self.available_balance) if self.available_balance is not None else 0.0,
            "pending_balance": float(self.pending_balance) if self.pending_balance is not None else 0.0,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class WalletLimitModel(BaseModel):
    __tablename__ = WalletTables.LIMITS

    country_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    max_wallets_per_user: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    daily_transfer_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=500000.00, nullable=False)
    daily_withdrawal_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=300000.00, nullable=False)
    daily_payment_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=1000000.00, nullable=False)
    max_balance: Mapped[float] = mapped_column(Numeric(18, 2), default=5000000.00, nullable=False)

    def to_dict(self) -> dict:
        return {
            "country_code": self.country_code,
            "max_wallets_per_user": self.max_wallets_per_user,
            "daily_transfer_limit": float(self.daily_transfer_limit),
            "daily_withdrawal_limit": float(self.daily_withdrawal_limit),
            "daily_payment_limit": float(self.daily_payment_limit),
            "max_balance": float(self.max_balance),
        }


class WalletSecurityModel(BaseModel):
    __tablename__ = WalletTables.SECURITY

    wallet_id: Mapped[int] = mapped_column(Integer, ForeignKey(f"{WalletTables.WALLETS}.id"), primary_key=True)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(SADateTime, nullable=True)

    wallet: Mapped["WalletModel"] = relationship("WalletModel", back_populates="security_record", lazy="selectin")

    def to_dict(self) -> dict:
        return {
            "wallet_id": self.wallet_id,
            "has_pin": bool(self.pin_hash),
            "failed_attempts": self.failed_attempts,
            "is_locked": bool(self.locked_until and self.locked_until > datetime.utcnow()),
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
        }


class WalletBranchConfigModel(BaseModel):
    __tablename__ = WalletTables.BRANCH_CONFIGS

    branch_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_wallets_per_user: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "branch_id": self.branch_id,
            "is_enabled": self.is_enabled,
            "max_wallets_per_user": self.max_wallets_per_user,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

