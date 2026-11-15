from __future__ import annotations
from decimal import Decimal
from typing import Any
from core.module import ApplicationModule, Permission
from .controllers.web import WalletWebController
from .controllers.api import WalletAPIController
from .services.wallet_service import WalletService
from .services.wallet_balance_service import WalletBalanceService
from .services.transfer_service import TransferService
from .services.payment_service import PaymentService
from .services.deposit_service import DepositService
from .services.withdrawal_service import WithdrawalService
from .services.wallet_security_service import WalletSecurityService
from .repositories.wallet_repository import WalletRepository
from .services.wallet_event_publisher import WalletEventPublisher


class MelodiWalletModule(ApplicationModule):

    def _get_permissions(self):
        return [
            Permission(self, "wallet:read", "Consulter les portefeuilles et les relevés de transactions"),
            Permission(self, "wallet:write", "Créer et modifier les portefeuilles"),
            Permission(self, "wallet:create", "Créer de nouveaux portefeuilles numériques"),
            Permission(self, "wallet:deposit", "Approvisionner un portefeuille numérique"),
            Permission(self, "wallet:withdraw", "Effectuer un retrait de portefeuille"),
            Permission(self, "wallet:transfer", "Effectuer un transfert inter-portefeuilles"),
            Permission(self, "wallet:pay_invoice", "Régler des factures via portefeuille"),
            Permission(self, "wallet:view_transactions", "Consulter le grand livre des transactions"),
            Permission(self, "wallet:manage_limits", "Gérer les plafonds et limites par pays"),
            Permission(self, "wallet:admin", "Administration complète des portefeuilles"),
        ]

    async def run_dev_migrations(self):
        """Création automatique des tables du module Wallet."""
        from .models.wallet_model import (
            WalletModel,
            WalletTransactionModel,
            WalletTransferModel,
            WalletBalanceModel,
            WalletLimitModel,
            WalletSecurityModel,
            WalletBranchConfigModel,
        )

        await self.app.db.create_all([
            WalletModel,
            WalletTransactionModel,
            WalletTransferModel,
            WalletBalanceModel,
            WalletLimitModel,
            WalletSecurityModel,
            WalletBranchConfigModel,
        ])

        try:
            from .config import WalletTables
            await self.app.db.execute(
                f"ALTER TABLE {WalletTables.WALLETS} ADD COLUMN IF NOT EXISTS branch_id VARCHAR(100);",
                query_type="write"
            )
        except Exception as e:
            print(f"Error adding branch_id to wallets table: {e}")

    async def load(self):
        """Initialisation et démarrage du module Wallet."""
        self.permissions = self._get_permissions()

        # Migrations dev
        if self.app.server.app.debug:
            await self.run_dev_migrations()

        # Enregistrement des routes d'administration Web
        self.admin_router.add_route("", WalletWebController.admin_dashboard, methods=["GET", "POST"])
        self.admin_router.add_route("/", WalletWebController.admin_dashboard, methods=["GET", "POST"])
        self.admin_router.add_route("/detail", WalletWebController.admin_wallet_detail, methods=["GET", "POST"])
        self.admin_router.add_route("/limits", WalletWebController.admin_limits, methods=["GET", "POST"])
        self.admin_router.add_route("/branches", WalletWebController.admin_branches, methods=["GET", "POST"])

        # Enregistrement des routes API REST
        self.api_router.add_route("/wallets", WalletAPIController.create_wallet, methods=["POST"])
        self.api_router.add_route("/wallets", WalletAPIController.list_wallets, methods=["GET"])
        self.api_router.add_route("/wallets/transfer", WalletAPIController.transfer, methods=["POST"])
        self.api_router.add_route("/wallets/pay-invoice", WalletAPIController.pay_invoice, methods=["POST"])
        self.api_router.add_route("/wallets/transfers", WalletAPIController.list_transfers, methods=["GET"])
        self.api_router.add_route("/wallets/{id}", WalletAPIController.get_wallet, methods=["GET"])
        self.api_router.add_route("/wallets/{id}/balance", WalletAPIController.get_balance, methods=["GET"])
        self.api_router.add_route("/wallets/{id}/transactions", WalletAPIController.get_transactions, methods=["GET"])
        self.api_router.add_route("/wallets/{id}/deposit", WalletAPIController.deposit, methods=["POST"])
        self.api_router.add_route("/wallets/{id}/withdraw", WalletAPIController.withdraw, methods=["POST"])
        self.api_router.add_route("/wallets/{id}/pin", WalletAPIController.set_pin, methods=["POST"])

        # Enregistrement des actions inter-modules
        self._register_actions()

        # Enregistrement de la navigation dans le menu admin
        self.register_navigation(
            id="wallet_root",
            label="Portefeuilles",
            icon="name=account_balance_wallet&fill=white",
            url="/admin/melodi_wallet",
            priority=65,
            children=[
                {"label": "Tous les Portefeuilles", "icon": "name=wallet&fill=white", "url": "/admin/melodi_wallet"},
                {"label": "Agences Autorisées", "icon": "name=domain&fill=white", "url": "/admin/melodi_wallet/branches"},
                {"label": "Plafonds & Limites", "icon": "name=tune&fill=white", "url": "/admin/melodi_wallet/limits"},
            ]
        )


        # Déclaration des événements auprès du module comptable
        await WalletEventPublisher.register_accounting_events(self)

        # Enregistrement des outils auprès de melodi_mcp (Zone de contribution + Intégration dynamique)
        for tool_dict in self._get_mcp_tools_definitions():
            self.register_contribution("mcp_tools", tool_dict)
        await self.integration_with_module("melodi_mcp", self._register_mcp_tools)

    def _get_mcp_tools_definitions(self) -> list[dict[str, Any]]:
        """Définit les outils MCP exposés aux assistants IA pour la gestion des portefeuilles."""
        mod_name = self.dirname or "melodi_wallet"
        return [
            {
                "name": "wallet_get_balance",
                "description": (
                    "Consulte le solde disponible, le solde en attente et la devise d'un portefeuille numérique spécifique via son ID."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": True,
                "destructive": False,
                "required_permissions": ["wallet:read"],
                "handler": f"{mod_name}:get_wallet_balance",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "wallet_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Identifiant numérique du portefeuille."
                        }
                    },
                    "required": ["wallet_id"],
                    "additionalProperties": False
                }
            },
            {
                "name": "wallet_get_user_wallets",
                "description": (
                    "Liste l'ensemble des portefeuilles numériques appartenant à un utilisateur avec solde et agence de rattachement."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": True,
                "destructive": False,
                "required_permissions": ["wallet:read"],
                "handler": f"{mod_name}:get_user_wallets",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "Identifiant unique de l'utilisateur ERP (ex: 'usr-123')."
                        },
                        "branch_id": {
                            "type": "string",
                            "description": "Identifiant optionnel d'une agence pour filtrer les portefeuilles."
                        }
                    },
                    "required": ["user_id"],
                    "additionalProperties": False
                }
            },
            {
                "name": "wallet_get_transactions",
                "description": (
                    "Consulte l'historique paginé des transactions (débits, crédits, références, dates) d'un portefeuille."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": True,
                "destructive": False,
                "required_permissions": ["wallet:read"],
                "handler": f"{mod_name}:get_wallet_transactions",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "wallet_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Identifiant numérique du portefeuille."
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 50,
                            "description": "Nombre maximum d'écritures à retourner."
                        },
                        "type_filter": {
                            "type": "string",
                            "description": "Filtre optionnel sur le type de transaction (ex: 'DEPOSIT', 'TRANSFER', 'WITHDRAWAL', 'PAYMENT')."
                        }
                    },
                    "required": ["wallet_id"],
                    "additionalProperties": False
                }
            },
            {
                "name": "wallet_create_wallet",
                "description": (
                    "Crée un nouveau portefeuille numérique pour un utilisateur dans une agence ou un pays donné."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": False,
                "destructive": False,
                "required_permissions": ["wallet:create"],
                "handler": f"{mod_name}:create_wallet",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "Identifiant de l'utilisateur propriétaire."
                        },
                        "name": {
                            "type": "string",
                            "description": "Libellé ou nom du portefeuille (ex: 'Portefeuille Principal', 'Épargne')."
                        },
                        "branch_id": {
                            "type": "string",
                            "description": "Identifiant de l'agence de rattachement."
                        },
                        "country_code": {
                            "type": "string",
                            "description": "Code ISO du pays (ex: 'CM', 'CI', 'SN')."
                        },
                        "is_default": {
                            "type": "boolean",
                            "default": False,
                            "description": "Définir comme portefeuille par défaut de l'utilisateur."
                        }
                    },
                    "required": ["user_id"],
                    "additionalProperties": False
                }
            },
            {
                "name": "wallet_deposit_funds",
                "description": (
                    "Crédite un montant sur un portefeuille numérique (dépôt espèces ou approvisionnement)."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": False,
                "destructive": False,
                "required_permissions": ["wallet:deposit"],
                "handler": f"{mod_name}:deposit_funds",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "wallet_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Identifiant numérique du portefeuille à créditer."
                        },
                        "amount": {
                            "type": "number",
                            "minimum": 0.01,
                            "description": "Montant positif à créditer."
                        },
                        "description": {
                            "type": "string",
                            "description": "Motif ou libellé de l'approvisionnement."
                        },
                        "reference": {
                            "type": "string",
                            "description": "Référence externe unique du versement."
                        }
                    },
                    "required": ["wallet_id", "amount"],
                    "additionalProperties": False
                }
            },
            {
                "name": "wallet_transfer_funds",
                "description": (
                    "Transfère un montant d'un portefeuille source vers un portefeuille de destination. "
                    "Opération financière nécessitant une validation explicite de l'utilisateur."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": False,
                "destructive": False,
                "confirmation_required": True,
                "required_permissions": ["wallet:transfer"],
                "handler": f"{mod_name}:transfer_funds",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "source_wallet_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Identifiant du portefeuille débité."
                        },
                        "destination_wallet_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Identifiant du portefeuille crédité."
                        },
                        "amount": {
                            "type": "number",
                            "minimum": 0.01,
                            "description": "Montant du transfert."
                        },
                        "description": {
                            "type": "string",
                            "description": "Motif du transfert de fonds."
                        },
                        "pin": {
                            "type": "string",
                            "description": "Code PIN de sécurité si requis par le compte source."
                        }
                    },
                    "required": ["source_wallet_id", "destination_wallet_id", "amount"],
                    "additionalProperties": False
                }
            },
            {
                "name": "wallet_pay_invoice",
                "description": (
                    "Règle une facture client impayée depuis un portefeuille numérique. "
                    "Opération financière avec confirmation explicite requise."
                ),
                "module": mod_name,
                "version": "1.0.0",
                "category": "finance",
                "read_only": False,
                "destructive": False,
                "confirmation_required": True,
                "required_permissions": ["wallet:pay_invoice"],
                "handler": f"{mod_name}:pay_invoice",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "wallet_id": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "Identifiant du portefeuille à débiter."
                        },
                        "invoice_id": {
                            "type": "string",
                            "description": "Identifiant unique de la facture à régler."
                        },
                        "amount": {
                            "type": "number",
                            "minimum": 0.01,
                            "description": "Montant à régler."
                        },
                        "description": {
                            "type": "string",
                            "description": "Libellé de paiement."
                        },
                        "pin": {
                            "type": "string",
                            "description": "Code PIN de sécurité si requis."
                        }
                    },
                    "required": ["wallet_id", "invoice_id", "amount"],
                    "additionalProperties": False
                }
            }
        ]

    async def _register_mcp_tools(self):
        """Enregistre les outils auprès du module melodi_mcp."""
        await self.execute_action("melodi_mcp", "register_tools", {
            "tools": self._get_mcp_tools_definitions()
        })

    def _register_actions(self):
        """Enregistre les actions exposées aux autres modules."""
        self.add_action("create_wallet", self.action_create_wallet)
        self.add_action("get_user_wallets", self.action_get_user_wallets)
        self.add_action("get_wallet", self.action_get_wallet)
        self.add_action("get_authorized_branches", self.action_get_authorized_branches)
        self.add_action("get_wallet_balance", self.action_get_wallet_balance)
        self.add_action("get_wallet_transactions", self.action_get_wallet_transactions)
        self.add_action("deposit_funds", self.action_deposit_funds)
        self.add_action("withdraw_funds", self.action_withdraw_funds)
        self.add_action("transfer_funds", self.action_transfer_funds)
        self.add_action("pay_invoice", self.action_pay_invoice)
        self.add_action("set_wallet_pin", self.action_set_wallet_pin)

    # --- Handlers d'actions inter-modules ---

    async def action_get_authorized_branches(self, payload: dict) -> dict:
        user_id = payload.get("user_id") if isinstance(payload, dict) else None
        async with self.app.db.get_session() as session:
            try:
                branches = await WalletService.get_authorized_branches(session, user_id=user_id)
                return {"status": "success", "branches": branches}
            except Exception as e:
                return {"status": "error", "message": str(e), "branches": []}

    async def action_create_wallet(self, payload: dict) -> dict:
        async with self.app.db.get_session() as session:
            try:
                wallet = await WalletService.create_wallet(
                    session=session,
                    user_id=payload.get("user_id"),
                    branch_id=payload.get("branch_id"),
                    country_code=payload.get("country_code"),
                    name=payload.get("name"),
                    is_default=payload.get("is_default", False),
                    module_instance=self
                )
                await session.commit()
                wd = wallet.to_dict()
                if wallet.branch_id:
                    from modules.melodi_branches.models.branch_model import BranchModel
                    branch = await session.get(BranchModel, str(wallet.branch_id))
                    if branch:
                        wd["branch_name"] = branch.name
                return {"status": "success", "wallet": wd}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_get_user_wallets(self, payload: dict) -> dict:
        user_id = payload.get("user_id")
        branch_id = payload.get("branch_id")
        async with self.app.db.get_session() as session:
            try:
                wallets = await WalletService.get_user_wallets(session, user_id, branch_id=branch_id)
                wallet_dicts = []
                branch_ids = {w.branch_id for w in wallets if w.branch_id}
                branches_map = {}
                if branch_ids:
                    from modules.melodi_branches.models.branch_model import BranchModel
                    from sqlalchemy import select
                    stmt = select(BranchModel).where(BranchModel.branch_id.in_(branch_ids))
                    res = await session.execute(stmt)
                    for b in res.scalars().all():
                        branches_map[b.branch_id] = b.name

                for w in wallets:
                    wd = w.to_dict()
                    if w.branch_id and w.branch_id in branches_map:
                        wd["branch_name"] = branches_map[w.branch_id]
                    wallet_dicts.append(wd)

                return {"status": "success", "wallets": wallet_dicts}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_get_wallet(self, payload: dict) -> dict:
        wallet_id = int(payload.get("wallet_id"))
        async with self.app.db.get_session() as session:
            try:
                wallet = await WalletService.get_wallet(session, wallet_id)
                wd = wallet.to_dict()
                if wallet.branch_id:
                    from modules.melodi_branches.models.branch_model import BranchModel
                    branch = await session.get(BranchModel, str(wallet.branch_id))
                    if branch:
                        wd["branch_name"] = branch.name
                return {"status": "success", "wallet": wd}
            except Exception as e:
                return {"status": "error", "message": str(e)}


    async def action_get_wallet_balance(self, payload: dict) -> dict:
        wallet_id = payload.get("wallet_id")
        async with self.app.db.get_session() as session:
            try:
                avail, pend = await WalletBalanceService.get_balance(session, int(wallet_id))
                return {
                    "status": "success",
                    "wallet_id": wallet_id,
                    "available_balance": float(avail),
                    "pending_balance": float(pend)
                }
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_get_wallet_transactions(self, payload: dict) -> dict:
        wallet_id = int(payload.get("wallet_id"))
        type_filter = payload.get("type_filter")
        limit = int(payload.get("limit", 50))
        async with self.app.db.get_session() as session:
            try:
                txs = await WalletRepository.get_wallet_transactions(
                    session=session,
                    wallet_id=wallet_id,
                    type_filter=type_filter,
                    limit=limit
                )
                return {"status": "success", "transactions": [tx.to_dict() for tx in txs]}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_deposit_funds(self, payload: dict) -> dict:
        async with self.app.db.get_session() as session:
            try:
                tx = await DepositService.deposit_funds(
                    session=session,
                    wallet_id=int(payload.get("wallet_id")),
                    amount=Decimal(str(payload.get("amount"))),
                    description=payload.get("description"),
                    reference=payload.get("reference"),
                    module_instance=self
                )
                await session.commit()
                return {"status": "success", "transaction": tx.to_dict()}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_withdraw_funds(self, payload: dict) -> dict:
        async with self.app.db.get_session() as session:
            try:
                tx = await WithdrawalService.request_withdrawal(
                    session=session,
                    wallet_id=int(payload.get("wallet_id")),
                    amount=Decimal(str(payload.get("amount"))),
                    pin=payload.get("pin"),
                    description=payload.get("description"),
                    module_instance=self
                )
                if payload.get("auto_confirm", True):
                    tx = await WithdrawalService.confirm_withdrawal(
                        session=session,
                        transaction_id=tx.id,
                        approve=True,
                        module_instance=self
                    )
                await session.commit()
                return {"status": "success", "transaction": tx.to_dict()}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_transfer_funds(self, payload: dict) -> dict:
        async with self.app.db.get_session() as session:
            try:
                transfer_rec, tx_debit, tx_credit = await TransferService.transfer_funds(
                    session=session,
                    source_wallet_id=int(payload.get("source_wallet_id")),
                    destination_wallet_id=int(payload.get("destination_wallet_id")),
                    amount=Decimal(str(payload.get("amount"))),
                    pin=payload.get("pin"),
                    description=payload.get("description"),
                    module_instance=self
                )
                await session.commit()
                return {"status": "success", "transfer": transfer_rec.to_dict()}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_pay_invoice(self, payload: dict) -> dict:
        async with self.app.db.get_session() as session:
            try:
                tx = await PaymentService.pay_invoice(
                    session=session,
                    wallet_id=int(payload.get("wallet_id")),
                    invoice_id=payload.get("invoice_id"),
                    amount=Decimal(str(payload.get("amount"))),
                    pin=payload.get("pin"),
                    description=payload.get("description"),
                    module_instance=self
                )
                await session.commit()
                return {"status": "success", "transaction": tx.to_dict()}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def action_set_wallet_pin(self, payload: dict) -> dict:
        async with self.app.db.get_session() as session:
            try:
                sec = await WalletSecurityService.set_wallet_pin(
                    session=session,
                    wallet_id=int(payload.get("wallet_id")),
                    pin=payload.get("pin")
                )
                await session.commit()
                return {"status": "success", "security": sec.to_dict()}
            except Exception as e:
                return {"status": "error", "message": str(e)}


module = MelodiWalletModule(
    name="melodi_wallet",
    router_name="melodi_wallet"
)
