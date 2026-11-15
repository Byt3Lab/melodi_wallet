from decimal import Decimal
from core.routing import Request, Response

from ..services.wallet_service import WalletService
from ..services.ledger_service import LedgerService
from ..services.deposit_service import DepositService
from ..services.withdrawal_service import WithdrawalService
from ..services.transfer_service import TransferService
from ..services.payment_service import PaymentService
from ..services.wallet_security_service import WalletSecurityService
from ..services.wallet_balance_service import WalletBalanceService
from ..repositories.wallet_repository import WalletRepository
from sqlalchemy import select
from ..models.wallet_model import WalletTransferModel


class WalletAPIController:

    @staticmethod
    async def create_wallet(request: Request, response: Response):
        data = request.json or {}
        user_id = data.get("user_id") or "admin"
        country_code = data.get("country_code")
        name = data.get("name")
        is_default = bool(data.get("is_default", False))

        if not country_code or not name:
            return response.render_json({
                "status": "error",
                "message": "Paramètres country_code et name requis."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            try:
                wallet = await WalletService.create_wallet(
                    session=session,
                    user_id=user_id,
                    country_code=country_code,
                    name=name,
                    is_default=is_default,
                    module_instance=request.module
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "data": wallet.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)

    @staticmethod
    async def list_wallets(request: Request, response: Response):
        user_id = request.query.get("user_id") or "admin"
        async with request.module.app.db.get_session() as session:
            wallets = await WalletService.get_user_wallets(session, user_id)
            return response.render_json({
                "status": "success",
                "count": len(wallets),
                "data": [w.to_dict() for w in wallets]
            })

    @staticmethod
    async def get_wallet(request: Request, response: Response):
        wallet_id = int(request.path_params.get("id") or request.query.get("id"))
        async with request.module.app.db.get_session() as session:
            try:
                wallet = await WalletService.get_wallet(session, wallet_id)
                return response.render_json({
                    "status": "success",
                    "data": wallet.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=404)

    @staticmethod
    async def get_balance(request: Request, response: Response):
        wallet_id = int(request.path_params.get("id") or request.query.get("id"))
        async with request.module.app.db.get_session() as session:
            try:
                wallet = await WalletService.get_wallet(session, wallet_id)
                available, pending = await WalletBalanceService.get_balance(session, wallet_id)
                return response.render_json({
                    "status": "success",
                    "wallet_id": wallet_id,
                    "currency_code": wallet.currency_code,
                    "available_balance": float(available),
                    "pending_balance": float(pending)
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=404)

    @staticmethod
    async def get_transactions(request: Request, response: Response):
        wallet_id = int(request.path_params.get("id") or request.query.get("id"))
        type_filter = request.query.get("type")
        status_filter = request.query.get("status")

        async with request.module.app.db.get_session() as session:
            try:
                txs = await WalletRepository.get_wallet_transactions(
                    session,
                    wallet_id=wallet_id,
                    type_filter=type_filter,
                    status_filter=status_filter
                )
                return response.render_json({
                    "status": "success",
                    "count": len(txs),
                    "data": [tx.to_dict() for tx in txs]
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)

    @staticmethod
    async def deposit(request: Request, response: Response):
        wallet_id = int(request.path_params.get("id") or request.query.get("id"))
        data = request.json or {}
        amount = Decimal(str(data.get("amount", 0)))
        description = data.get("description")
        reference = data.get("reference")

        async with request.module.app.db.get_session() as session:
            try:
                tx = await DepositService.deposit_funds(
                    session=session,
                    wallet_id=wallet_id,
                    amount=amount,
                    description=description,
                    reference=reference,
                    module_instance=request.module
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "transaction": tx.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)

    @staticmethod
    async def withdraw(request: Request, response: Response):
        wallet_id = int(request.path_params.get("id") or request.query.get("id"))
        data = request.json or {}
        amount = Decimal(str(data.get("amount", 0)))
        pin = data.get("pin")
        description = data.get("description")
        auto_confirm = bool(data.get("auto_confirm", True))

        async with request.module.app.db.get_session() as session:
            try:
                tx = await WithdrawalService.request_withdrawal(
                    session=session,
                    wallet_id=wallet_id,
                    amount=amount,
                    pin=pin,
                    description=description,
                    module_instance=request.module
                )
                if auto_confirm:
                    tx = await WithdrawalService.confirm_withdrawal(
                        session=session,
                        transaction_id=tx.id,
                        approve=True,
                        module_instance=request.module
                    )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "transaction": tx.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)

    @staticmethod
    async def transfer(request: Request, response: Response):
        data = request.json or {}
        source_wallet_id = int(data.get("source_wallet_id"))
        destination_wallet_id = int(data.get("destination_wallet_id"))
        amount = Decimal(str(data.get("amount", 0)))
        pin = data.get("pin")
        description = data.get("description")

        async with request.module.app.db.get_session() as session:
            try:
                transfer_rec, tx_debit, tx_credit = await TransferService.transfer_funds(
                    session=session,
                    source_wallet_id=source_wallet_id,
                    destination_wallet_id=destination_wallet_id,
                    amount=amount,
                    pin=pin,
                    description=description,
                    module_instance=request.module
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "transfer": transfer_rec.to_dict(),
                    "debit_transaction": tx_debit.to_dict(),
                    "credit_transaction": tx_credit.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)

    @staticmethod
    async def pay_invoice(request: Request, response: Response):
        data = request.json or {}
        wallet_id = int(data.get("wallet_id"))
        invoice_id = data.get("invoice_id")
        amount = Decimal(str(data.get("amount", 0)))
        pin = data.get("pin")
        description = data.get("description")

        async with request.module.app.db.get_session() as session:
            try:
                tx = await PaymentService.pay_invoice(
                    session=session,
                    wallet_id=wallet_id,
                    invoice_id=invoice_id,
                    amount=amount,
                    pin=pin,
                    description=description,
                    module_instance=request.module
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "transaction": tx.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)

    @staticmethod
    async def list_transfers(request: Request, response: Response):
        wallet_id = request.query.get("wallet_id")
        async with request.module.app.db.get_session() as session:
            stmt = select(WalletTransferModel).order_by(WalletTransferModel.id.desc())
            if wallet_id:
                wid = int(wallet_id)
                stmt = stmt.where((WalletTransferModel.source_wallet_id == wid) | (WalletTransferModel.destination_wallet_id == wid))
            res = await session.execute(stmt)
            transfers = list(res.scalars().all())
            return response.render_json({
                "status": "success",
                "count": len(transfers),
                "data": [tr.to_dict() for tr in transfers]
            })

    @staticmethod
    async def set_pin(request: Request, response: Response):
        wallet_id = int(request.path_params.get("id") or request.query.get("id"))
        data = request.json or {}
        pin = data.get("pin")

        async with request.module.app.db.get_session() as session:
            try:
                sec = await WalletSecurityService.set_wallet_pin(session, wallet_id, pin)
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "data": sec.to_dict()
                })
            except Exception as e:
                return response.render_json({"status": "error", "message": str(e)}, status_code=400)
