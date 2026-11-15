from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from ..repositories.wallet_repository import WalletRepository
from ..models.wallet_model import WalletModel, WalletStatus
from .wallet_limit_service import WalletLimitService
from .wallet_event_publisher import WalletEventPublisher

# Reference mapping for Country -> Currency
COUNTRY_CURRENCY_MAP: Dict[str, str] = {
    "CM": "XAF", "CF": "XAF", "TD": "XAF", "CG": "XAF", "GA": "XAF", "GQ": "XAF",
    "CI": "XOF", "SN": "XOF", "ML": "XOF", "BF": "XOF", "NE": "XOF", "BJ": "XOF", "TG": "XOF", "GW": "XOF",
    "FR": "EUR", "DE": "EUR", "IT": "EUR", "ES": "EUR", "NL": "EUR", "BE": "EUR",
    "US": "USD", "CA": "CAD", "GB": "GBP", "CH": "CHF", "CN": "CNY", "AE": "AED", "IN": "INR", "JP": "JPY",
    "NG": "NGN", "GH": "GHS", "KE": "KES", "TZ": "TZS", "UG": "UGX", "RW": "RWF", "ZA": "ZAR", "MA": "MAD",
    "DZ": "DZD", "TN": "TND", "EG": "EGP", "CD": "CDF"
}


class WalletService:

    @staticmethod
    def resolve_country_code(val: Optional[str], default: str = "CM") -> str:
        if not val:
            return default
        val_clean = str(val).strip()
        if not val_clean:
            return default

        try:
            from core.utils.geo import load_countries
            countries = load_countries()
        except Exception:
            countries = []

        # 1. Exact match country_code (e.g. 'CM', 'FR')
        for c in countries:
            if c.get("country_code", "").upper() == val_clean.upper():
                return c["country_code"]

        # 2. Exact match country name (case-insensitive) (e.g. 'Cameroun', 'France')
        for c in countries:
            if c.get("name", "").lower() == val_clean.lower():
                return c["country_code"]

        # 3. 3-character alpha-3 prefix match (e.g. CMR -> CM, FRA -> FR)
        if len(val_clean) == 3:
            prefix = val_clean[:2].upper()
            for c in countries:
                if c.get("country_code", "").upper() == prefix:
                    return c["country_code"]

        # 4. Substring match on name (e.g. Côte d'Ivoire)
        val_lower = val_clean.lower()
        for c in countries:
            name_lower = c.get("name", "").lower()
            if val_lower in name_lower or name_lower in val_lower:
                return c["country_code"]

        # 5. Fallback if short code
        if len(val_clean) <= 3:
            return val_clean.upper()

        return default

    @staticmethod
    def get_currency_for_country(country_code: str) -> str:
        code = country_code.upper().strip()
        return COUNTRY_CURRENCY_MAP.get(code, "XAF")

    @staticmethod
    async def create_wallet(
        session: AsyncSession,
        user_id: str,
        country_code: Optional[str] = None,
        name: str = "",
        branch_id: Optional[str] = None,
        is_default: bool = False,
        module_instance=None
    ) -> WalletModel:
        # 1. Validation obligatoire de l'agence hébergeuse et du quota utilisateur par agence
        await WalletLimitService.validate_branch_wallet_limit(session, user_id, branch_id)

        # 2. Récupération des informations de l'agence (devise et pays de rattachement)
        from modules.melodi_branches.models.branch_model import BranchModel
        branch = await session.get(BranchModel, str(branch_id))
        if not branch:
            raise ValueError(f"Agence hébergeuse introuvable (ID: {branch_id}).")

        branch_currency = branch.currency_code if branch and branch.currency_code else "XAF"

        # Le pays de rattachement est celui de l'agence
        branch_country_raw = getattr(branch, "country", None)
        if not branch_country_raw and getattr(branch, "city_ref", None) and branch.city_ref and getattr(branch.city_ref, "region", None) and branch.city_ref.region.country:
            branch_country_raw = branch.city_ref.region.country.name or branch.city_ref.region.country.code_iso

        branch_country_code = WalletService.resolve_country_code(branch_country_raw) if branch_country_raw else None

        # Priorité absolue au pays de l'agence
        c_code = branch_country_code or (country_code and WalletService.resolve_country_code(country_code)) or "CM"
        currency_code = branch_currency.upper().strip()

        # 3. Validation des plafonds par pays
        await WalletLimitService.validate_wallet_creation_limit(session, user_id, c_code)

        # 4. Si premier portefeuille pour l'utilisateur, forcer is_default = True
        existing = await WalletRepository.get_wallets_by_user(session, user_id)
        if len(existing) == 0:
            is_default = True

        wallet_name = name.strip() if name and name.strip() else f"Portefeuille ({currency_code})"

        # 5. Création de l'enregistrement
        wallet = await WalletRepository.create_wallet(
            session=session,
            user_id=user_id,
            branch_id=str(branch_id),
            country_code=c_code,
            currency_code=currency_code,
            name=wallet_name,
            is_default=is_default
        )

        # 6. Publication de l'événement
        if module_instance:
            await WalletEventPublisher.publish_event(module_instance, "WalletCreated", wallet.to_dict())

        return wallet


    @staticmethod
    async def get_user_wallets(session: AsyncSession, user_id: str, branch_id: Optional[str] = None) -> List[WalletModel]:
        return await WalletRepository.get_wallets_by_user(session, user_id, branch_id=branch_id)


    @staticmethod
    async def get_wallet(session: AsyncSession, wallet_id: int) -> WalletModel:
        wallet = await WalletRepository.get_wallet_by_id(session, wallet_id)
        if not wallet:
            raise ValueError(f"Portefeuille #{wallet_id} introuvable.")
        return wallet

    @staticmethod
    async def set_default_wallet(session: AsyncSession, user_id: str, wallet_id: int) -> WalletModel:
        wallets = await WalletRepository.get_wallets_by_user(session, user_id)
        target = None
        for w in wallets:
            if w.id == wallet_id:
                w.is_default = True
                target = w
            else:
                w.is_default = False
        if not target:
            raise ValueError(f"Portefeuille #{wallet_id} introuvable pour l'utilisateur {user_id}")
        await session.flush()
        return target

    @staticmethod
    async def update_wallet_status(session: AsyncSession, wallet_id: int, status: str) -> WalletModel:
        wallet = await WalletService.get_wallet(session, wallet_id)
        wallet.status = WalletStatus(status)
        await session.flush()
        return wallet

    @staticmethod
    async def get_authorized_branches(session: AsyncSession, user_id: Optional[str] = None) -> List[Dict]:
        from sqlalchemy import select
        from modules.melodi_branches.models.branch_model import BranchModel

        stmt = select(BranchModel).where(BranchModel.is_active == True)
        res = await session.execute(stmt)
        branches = list(res.scalars().all())

        configs = await WalletRepository.get_all_branch_configs(session)
        configs_map = {c.branch_id: c for c in configs}

        authorized = []
        for b in branches:
            cfg = configs_map.get(b.branch_id)
            is_enabled = cfg.is_enabled if cfg else True
            if not is_enabled:
                continue

            max_wallets = cfg.max_wallets_per_user if cfg else 1
            user_count = 0
            if user_id:
                user_count = await WalletRepository.count_user_wallets_in_branch(session, str(user_id), str(b.branch_id))

            country_code = WalletService.resolve_country_code(getattr(b, "country", None))
            authorized.append({
                "branch_id": str(b.branch_id),
                "name": b.name,
                "code": b.code or "",
                "currency_code": getattr(b, "currency_code", "XAF") or "XAF",
                "country": getattr(b, "country", "") or "",
                "country_code": country_code,
                "max_wallets_per_user": max_wallets,
                "user_wallets_count": user_count,
                "can_create": user_count < max_wallets if user_id else True,
            })
        return authorized

