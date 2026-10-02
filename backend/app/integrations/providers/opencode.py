"""OpenCode-specific configuration subset and runtime verification handler."""

import asyncio

from app.integrations.providers.base import ProviderRuntime


class OpenCodeProviderHandler:
    def __init__(self, runtime: ProviderRuntime, verify_timeout_seconds: float = 90):
        self.runtime = runtime
        self.verify_timeout_seconds = verify_timeout_seconds

    def validate_config(self, config: dict, auth: dict | None) -> list[dict]:
        violations = []
        providers = config.get("provider")
        if providers is not None and not isinstance(providers, dict):
            violations.append(_violation("providers_missing", "The 'provider' entry must be an object of provider definitions."))
        if not isinstance(providers, dict):
            # Native OpenCode configurations may omit custom providers entirely
            # and rely on built-in providers; their credentials come from
            # auth.json or provider options, so an absent or empty provider map
            # is acceptable.
            providers = {}
        inline_auth = False
        for provider_id, provider in providers.items():
            if not isinstance(provider_id, str) or not isinstance(provider, dict):
                violations.append(_violation("provider_invalid", "Each provider entry must be an object."))
                continue
            options = provider.get("options", {})
            if not isinstance(options, dict):
                violations.append(_violation("provider_options_invalid", f"Provider '{provider_id}' options must be an object."))
            elif isinstance(options.get("apiKey"), str) and options["apiKey"].strip():
                inline_auth = True
            models = provider.get("models")
            if models is not None:
                if not isinstance(models, dict):
                    violations.append(_violation("models_invalid", f"Provider '{provider_id}' models must be an object."))
                elif any(not isinstance(model, dict) for model in models.values()):
                    violations.append(_violation("model_invalid", f"Provider '{provider_id}' model entries must be objects."))

        selected_model = config.get("model")
        if selected_model is not None and (not isinstance(selected_model, str) or not selected_model.strip()):
            violations.append(_violation("model_invalid", "The selected model must be a non-empty string."))

        if auth is not None:
            if not isinstance(auth, dict):
                violations.append(_violation("auth_invalid", "auth.json must contain a provider object."))
            elif not any(_auth_entry_has_credentials(entry) for entry in auth.values()):
                violations.append(_violation("auth_missing", "auth.json does not contain provider credentials."))
        elif not inline_auth:
            violations.append(_violation("auth_missing", "Add provider credentials in auth.json or provider options."))
        # MCP and skills are deliberately not validated by provider setup.
        return violations

    async def list_models(self, user_id: str) -> list[str]:
        return await self.runtime.list_models(user_id)

    async def list_candidate_models(self, user_id: str, config: dict, auth: dict | None) -> list[str]:
        return await self.runtime.list_candidate_models(user_id, config, auth)

    async def verify_candidate_model(self, user_id: str, config: dict, auth: dict | None, model: str) -> dict:
        try:
            return await asyncio.wait_for(
                self.runtime.verify_candidate_model(user_id, config, auth, model),
                timeout=self.verify_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_TIMEOUT",
                    "message_key": "errors.provider.verification_timeout", "params": {"provider": "opencode"}}}

    async def verify_model(self, user_id: str, model: str) -> dict:
        try:
            result = await asyncio.wait_for(
                self.runtime.verify_model(user_id, model), timeout=self.verify_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_TIMEOUT",
                    "message_key": "errors.provider.verification_timeout", "params": {"provider": "opencode"}}}
        except Exception as exc:
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_FAILED",
                    "message_key": "errors.provider.verification_failed", "params": {"reason": type(exc).__name__}}}
        if result.get("ok"):
            return {"ok": True, "response_snippet": str(result.get("response_snippet", ""))[:240],
                    "latency_ms": int(result.get("latency_ms", 0))}
        return result


def _auth_entry_has_credentials(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(isinstance(entry.get(field), str) and entry[field].strip()
               for field in ("key", "access", "token", "refresh"))


def _violation(code: str, message: str) -> dict:
    return {"code": code, "message_key": f"errors.provider.{code}", "params": {}}
