from core import get_prefix_table
from core.db.base_module_tables import BaseModuleTables

MODULE_NAME = "melodi_wallet"
PREFIX_TABLE = get_prefix_table(MODULE_NAME)

class WalletTables(BaseModuleTables):
    """Centralisation dynamique des tables SQL du module Wallet."""
    WALLETS = f"{PREFIX_TABLE}wallets"
    TRANSACTIONS = f"{PREFIX_TABLE}transactions"
    TRANSFERS = f"{PREFIX_TABLE}transfers"
    BALANCES = f"{PREFIX_TABLE}balances"
    LIMITS = f"{PREFIX_TABLE}limits"
    SECURITY = f"{PREFIX_TABLE}security"
    BRANCH_CONFIGS = f"{PREFIX_TABLE}branch_configs"

