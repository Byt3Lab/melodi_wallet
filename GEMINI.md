# MELODI Wallet — Directives du Module Portefeuilles Virtuels (`modules/melodi_wallet/`)

Le module `melodi_wallet` fournit un système de portefeuilles virtuels et de sous-comptes prépayés pour les clients, employés ou partenaires de l'entreprise.

---

## 1. Modèles et Schéma de Données

- **`WalletModel`** (`ml_wlt_wallets`) : Portefeuille virtuel (`wallet_id`, `owner_id`, `balance`, `currency`, `is_active`).
- **`SubWalletModel`** (`ml_wlt_sub_wallets`) : Sous-portefeuilles dédiés (ex: cantine, carburant, primes).
- **`WalletTransactionModel`** (`ml_wlt_transactions`) : Mouvements de crédits / débits virtuels.

---

## 2. Directives Métier

1. **Sécurité et Anti-Double Dépense** :
   Les opérations de débit d'un portefeuille virtuel doivent obligatoirement vérifier la disponibilité du solde avant validation, avec un verrouillage de ligne (Row Locking `SELECT ... FOR UPDATE` si nécessaire).
2. **Paiement POS & Caisse** :
   Le module `melodi_retail` peut interroger et débiter le portefeuille d'un client lors d'un règlement en caisse via les API/Services exposés par `melodi_wallet`.
