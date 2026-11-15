from typing import Any, Dict


class WalletEventPublisher:

    @staticmethod
    async def register_accounting_events(module_instance):
        """
        Déclare les événements métier auprès du module comptable (melodi_accounting) via le hook d'action register_accounting_event.
        """
        if not hasattr(module_instance, "app") or not module_instance.app:
            return

        events_to_register = [
            {
                "origin_module": "melodi_wallet",
                "event_name": "WalletFunded",
                "opcode": "WALLET_FUND",
                "description": "Approvisionnement du portefeuille numérique client"
            },
            {
                "origin_module": "melodi_wallet",
                "event_name": "WalletWithdrawn",
                "opcode": "WALLET_WITHDRAW",
                "description": "Retrait de fonds du portefeuille numérique client"
            },
            {
                "origin_module": "melodi_wallet",
                "event_name": "WalletTransferred",
                "opcode": "WALLET_TRANSFER",
                "description": "Transfert d'argent inter-portefeuilles (débit)"
            },
            {
                "origin_module": "melodi_wallet",
                "event_name": "WalletPaymentCompleted",
                "opcode": "WALLET_PAY_INV",
                "description": "Règlement d'une facture MELODI via portefeuille numérique"
            },
        ]

        for ev in events_to_register:
            try:
                await module_instance.app.hook_manager.action.execute(
                    "melodi_accounting",
                    "register_accounting_event",
                    ev
                )
            except Exception as e:
                # melodi_accounting not loaded or optional
                pass

    @staticmethod
    async def publish_event(module_instance, event_name: str, payload: Dict[str, Any]):
        """
        Publie un événement sur le système d'écouteurs MELODI.
        """
        if hasattr(module_instance, "notify_event_listener"):
            await module_instance.notify_event_listener(event_name, payload)
        elif hasattr(module_instance, "app") and module_instance.app:
            await module_instance.app.hook_manager.event_listener.notify(
                "melodi_wallet",
                event_name,
                payload
            )
