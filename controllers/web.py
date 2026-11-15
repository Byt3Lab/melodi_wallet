from decimal import Decimal
from core.routing import Request, Response
from core.page_builder import Page, Component
from base.components import admin_layout

from ..services.wallet_service import WalletService, COUNTRY_CURRENCY_MAP
from ..services.ledger_service import LedgerService
from ..services.deposit_service import DepositService
from ..services.withdrawal_service import WithdrawalService
from ..services.transfer_service import TransferService
from ..services.payment_service import PaymentService
from ..services.wallet_security_service import WalletSecurityService
from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import WalletLimitModel


class WalletWebController:

    @staticmethod
    async def admin_dashboard(request: Request, response: Response):
        import json
        user_raw = request.get_session("user_payload")
        user = json.loads(user_raw) if isinstance(user_raw, str) else (user_raw or {})
        session_branch_id = user.get("active_branch")
        current_admin_id = user.get("user_id") or "admin"

        # Parameters for filtering
        filter_user_id = request.query.get("user_id")
        filter_status = request.query.get("status")
        filter_search = request.query.get("q")
        filter_branch_id = request.query.get("branch_id")

        if request.method == "POST":
            form = request.form
            action_type = form.get("action_type")
            async with request.module.app.db.get_session() as session:
                try:
                    if action_type == "create_wallet":
                        target_user_id = form.get("client_user_id") or form.get("user_id") or current_admin_id
                        branch_id = form.get("branch_id") or session_branch_id
                        await WalletService.create_wallet(
                            session=session,
                            user_id=target_user_id,
                            branch_id=branch_id,
                            country_code=form.get("country_code"),
                            name=form.get("name"),
                            is_default=form.get("is_default") == "on",
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "change_status":
                        wallet_id = int(form.get("wallet_id"))
                        new_status = form.get("status")
                        await WalletService.update_wallet_status(session, wallet_id, new_status)
                        await session.commit()
                    elif action_type == "set_default":
                        wallet_id = int(form.get("wallet_id"))
                        target_user_id = form.get("user_id")
                        await WalletService.set_default_wallet(session, target_user_id, wallet_id)
                        await session.commit()
                    elif action_type == "deposit":
                        await DepositService.deposit_funds(
                            session=session,
                            wallet_id=int(form.get("wallet_id")),
                            amount=Decimal(form.get("amount")),
                            description=form.get("description"),
                            created_by=current_admin_id,
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "transfer":
                        await TransferService.transfer_funds(
                            session=session,
                            source_wallet_id=int(form.get("source_wallet_id")),
                            destination_wallet_id=int(form.get("destination_wallet_id")),
                            amount=Decimal(form.get("amount")),
                            pin=form.get("pin"),
                            description=form.get("description"),
                            created_by=current_admin_id,
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "withdraw":
                        tx = await WithdrawalService.request_withdrawal(
                            session=session,
                            wallet_id=int(form.get("wallet_id")),
                            amount=Decimal(form.get("amount")),
                            pin=form.get("pin"),
                            description=form.get("description"),
                            created_by=current_admin_id,
                            module_instance=request.module
                        )
                        await WithdrawalService.confirm_withdrawal(
                            session=session,
                            transaction_id=tx.id,
                            approve=True,
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "pay_invoice":
                        await PaymentService.pay_invoice(
                            session=session,
                            wallet_id=int(form.get("wallet_id")),
                            invoice_id=form.get("invoice_id"),
                            amount=Decimal(form.get("amount")),
                            pin=form.get("pin"),
                            description=form.get("description"),
                            created_by=current_admin_id,
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "set_pin":
                        await WalletSecurityService.set_wallet_pin(
                            session=session,
                            wallet_id=int(form.get("wallet_id")),
                            pin=form.get("pin")
                        )
                        await session.commit()
                except Exception as e:
                    print("Wallet action error:", e)

            redirect_url = "/admin/melodi_wallet"
            if filter_user_id:
                redirect_url += f"?user_id={filter_user_id}"
            return response.redirect(redirect_url)

        branches = []
        authorized_branches = []
        users = []
        users_map = {}
        async with request.module.app.db.get_session() as session:
            try:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                from modules.melodi_branches.models.branch_model import BranchModel
                from base.models.user_model import UserModel

                stmt_b = select(BranchModel).where(BranchModel.is_active == True)
                res_b = await session.execute(stmt_b)
                db_branches = list(res_b.scalars().all())

                branch_configs = await WalletRepository.get_all_branch_configs(session)
                cfg_map = {c.branch_id: c for c in branch_configs}

                for b in db_branches:
                    cfg = cfg_map.get(b.branch_id)
                    is_enabled = cfg.is_enabled if cfg else True
                    max_wallets = cfg.max_wallets_per_user if cfg else 1
                    b_country = b.country or ""
                    if not b_country and getattr(b, "city_ref", None) and b.city_ref and getattr(b.city_ref, "region", None) and b.city_ref.region.country:
                        b_country = b.city_ref.region.country.name or b.city_ref.region.country.code_iso
                    b_country_code = WalletService.resolve_country_code(b_country)
                    b_info = {
                        "id": b.branch_id,
                        "name": b.name,
                        "code": b.code or "",
                        "currency_code": getattr(b, "currency_code", "XAF") or "XAF",
                        "country": b_country or b_country_code,
                        "country_code": b_country_code,
                        "is_enabled": is_enabled,
                        "max_wallets_per_user": max_wallets,
                    }
                    branches.append(b_info)
                    if is_enabled:
                        authorized_branches.append(b_info)

                stmt_u = select(UserModel).options(selectinload(UserModel.contact)).order_by(UserModel.username)
                res_u = await session.execute(stmt_u)
                for u in res_u.scalars().all():
                    c_name = u.contact.name if u.contact else u.username
                    c_email = u.contact.email if u.contact else ""
                    c_phone = u.contact.phone if u.contact else ""
                    u_info = {
                        "user_id": u.user_id,
                        "username": u.username,
                        "name": c_name,
                        "email": c_email,
                        "phone": c_phone
                    }
                    users.append(u_info)
                    users_map[u.user_id] = u_info
            except Exception as e:
                print(f"Notice loading branches/users in wallet controller: {e}")

            # Fetch wallets according to filter or all
            wallets = await WalletRepository.get_all_wallets(
                session=session,
                user_id=filter_user_id,
                search=filter_search,
                status=filter_status,
                branch_id=filter_branch_id,
                limit=100
            )

            all_wallets = await WalletRepository.get_all_wallets(session=session, limit=200)
            global_stats = await WalletRepository.get_global_stats(session=session)

            recent_transactions = []
            if wallets:
                recent_transactions = await WalletRepository.get_wallet_transactions(session, wallets[0].id, limit=10)

        # Attach owner info and branch info to wallet dicts / objects for template display
        branches_map = {str(b["id"]): b for b in branches}
        for w in wallets:
            w.owner_info = users_map.get(w.user_id, {"user_id": w.user_id, "username": w.user_id, "name": w.user_id, "email": "", "phone": ""})
            w.branch_info = branches_map.get(str(w.branch_id), {
                "id": w.branch_id,
                "name": w.branch_id or "Non assignée",
                "country": w.country_code,
                "country_code": w.country_code,
                "currency_code": w.currency_code
            })

        countries = [{"code": k, "currency": v} for k, v in COUNTRY_CURRENCY_MAP.items()]

        content = Component(module_name="melodi_wallet", name="admin_wallets", context={
            "wallets": wallets,
            "all_wallets": all_wallets,
            "recent_transactions": recent_transactions,
            "active_user_id": filter_user_id or "all",
            "users": users,
            "users_map": users_map,
            "global_stats": global_stats,
            "countries": countries,
            "branches": branches,
            "branches_map": branches_map,
            "authorized_branches": authorized_branches,
            "session_branch_id": session_branch_id,
            "filter_search": filter_search or "",
            "filter_status": filter_status or "",
            "filter_user_id": filter_user_id or "",
            "filter_branch_id": filter_branch_id or "",
        })
        page = Page("Portefeuilles Numériques", admin_layout(content))
        return await response.render_page(page)


    @staticmethod
    async def admin_wallet_detail(request: Request, response: Response):
        wallet_id = int(request.query.get("id") or 1)
        type_filter = request.query.get("type")
        status_filter = request.query.get("status")

        if request.method == "POST":
            form = request.form
            action_type = form.get("action_type")
            async with request.module.app.db.get_session() as session:
                try:
                    if action_type == "change_status":
                        new_status = form.get("status")
                        await WalletService.update_wallet_status(session, wallet_id, new_status)
                        await session.commit()
                    elif action_type == "set_default":
                        target_user_id = form.get("user_id")
                        await WalletService.set_default_wallet(session, target_user_id, wallet_id)
                        await session.commit()
                    elif action_type == "deposit":
                        await DepositService.deposit_funds(
                            session=session,
                            wallet_id=wallet_id,
                            amount=Decimal(form.get("amount")),
                            description=form.get("description"),
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "withdraw":
                        tx = await WithdrawalService.request_withdrawal(
                            session=session,
                            wallet_id=wallet_id,
                            amount=Decimal(form.get("amount")),
                            pin=form.get("pin"),
                            description=form.get("description"),
                            module_instance=request.module
                        )
                        await WithdrawalService.confirm_withdrawal(
                            session=session,
                            transaction_id=tx.id,
                            approve=True,
                            module_instance=request.module
                        )
                        await session.commit()
                    elif action_type == "set_pin":
                        await WalletSecurityService.set_wallet_pin(
                            session=session,
                            wallet_id=wallet_id,
                            pin=form.get("pin")
                        )
                        await session.commit()
                except Exception as e:
                    print(f"Error handling wallet action in detail view: {e}")
            return response.redirect(f"/admin/melodi_wallet/detail?id={wallet_id}")

        owner_info = None
        async with request.module.app.db.get_session() as session:
            wallet = await WalletService.get_wallet(session, wallet_id)
            transactions = await WalletRepository.get_wallet_transactions(
                session,
                wallet_id=wallet_id,
                type_filter=type_filter,
                status_filter=status_filter,
                limit=100
            )

            try:
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                from base.models.user_model import UserModel
                stmt_u = select(UserModel).options(selectinload(UserModel.contact)).where(UserModel.user_id == str(wallet.user_id))
                res_u = await session.execute(stmt_u)
                u_obj = res_u.scalar_one_or_none()
                if u_obj:
                    owner_info = {
                        "user_id": u_obj.user_id,
                        "username": u_obj.username,
                        "name": u_obj.contact.name if u_obj.contact else u_obj.username,
                        "email": u_obj.contact.email if u_obj.contact else "",
                        "phone": u_obj.contact.phone if u_obj.contact else "",
                    }
            except Exception as e:
                print(f"Notice fetching owner info: {e}")

        content = Component(module_name="melodi_wallet", name="admin_wallet_detail", context={
            "wallet": wallet,
            "owner_info": owner_info,
            "transactions": transactions,
            "type_filter": type_filter,
            "status_filter": status_filter,
        })
        page = Page(f"Détail Portefeuille - {wallet.name}", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_limits(request: Request, response: Response):
        if request.method == "POST":
            form = request.form
            country_code = form.get("country_code").upper().strip()
            async with request.module.app.db.get_session() as session:
                limit_obj = await WalletRepository.get_wallet_limits(session, country_code)
                limit_obj.max_wallets_per_user = int(form.get("max_wallets_per_user") or 3)
                limit_obj.daily_transfer_limit = float(form.get("daily_transfer_limit") or 500000.0)
                limit_obj.daily_withdrawal_limit = float(form.get("daily_withdrawal_limit") or 300000.0)
                limit_obj.daily_payment_limit = float(form.get("daily_payment_limit") or 1000000.0)
                limit_obj.max_balance = float(form.get("max_balance") or 5000000.0)
                await session.commit()
            return response.redirect("/admin/melodi_wallet/limits")

        async with request.module.app.db.get_session() as session:
            from sqlalchemy import select
            stmt = select(WalletLimitModel)
            res = await session.execute(stmt)
            limits = list(res.scalars().all())

        content = Component(module_name="melodi_wallet", name="admin_limits", context={
            "limits": limits,
            "countries": COUNTRY_CURRENCY_MAP,
        })
        page = Page("Plafonds & Limites par Pays", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_branches(request: Request, response: Response):
        if request.method == "POST":
            form = request.form
            branch_id = form.get("branch_id")
            is_enabled = form.get("is_enabled") == "on"
            max_wallets_per_user = int(form.get("max_wallets_per_user") or 1)

            async with request.module.app.db.get_session() as session:
                config = await WalletRepository.get_branch_config(session, branch_id)
                config.is_enabled = is_enabled
                config.max_wallets_per_user = max_wallets_per_user
                await session.commit()
            return response.redirect("/admin/melodi_wallet/branches")

        branch_configs_map = {}
        all_branches = []
        async with request.module.app.db.get_session() as session:
            try:
                from sqlalchemy import select
                from modules.melodi_branches.models.branch_model import BranchModel
                stmt_b = select(BranchModel).where(BranchModel.is_active == True)
                res_b = await session.execute(stmt_b)
                db_branches = list(res_b.scalars().all())

                configs = await WalletRepository.get_all_branch_configs(session)
                for c in configs:
                    branch_configs_map[c.branch_id] = c

                for b in db_branches:
                    cfg = branch_configs_map.get(b.branch_id)
                    all_branches.append({
                        "branch_id": b.branch_id,
                        "name": b.name,
                        "code": b.code or "",
                        "currency_code": getattr(b, "currency_code", "XAF") or "XAF",
                        "country": b.country or "",
                        "is_enabled": cfg.is_enabled if cfg else True,
                        "max_wallets_per_user": cfg.max_wallets_per_user if cfg else 1,
                    })
            except Exception as e:
                print(f"Error loading branch configs: {e}")

        content = Component(module_name="melodi_wallet", name="admin_branches", context={
            "branches": all_branches,
        })
        page = Page("Agences Autorisées à Héberger des Portefeuilles", admin_layout(content))
        return await response.render_page(page)

