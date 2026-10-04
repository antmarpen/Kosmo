"""OpenCode-specific configuration subset and runtime verification handler."""

import asyncio

from app.integrations.providers.base import ProviderRuntime


class OpenCodeProviderHandler:
    def __init__(self, runtime: ProviderRuntime, verify_timeout_seconds: float = 90):
        self.runtime = runtime
        self.verify_timeout_seconds = verify_timeout_seconds

    def validate_config(self, config: dict, auth: list | None) -> list[dict]:
        violations = []
        providers = config.get("providers")
        if providers is None or not isinstance(providers, dict):
            violations.append(_violation("providers_invalid", "The 'providers' entry must be an object of provider definitions."))
        if "provider" in config:
            violations.append(_violation("legacy_format_requires_conversion", "Legacy provider configuration requires conversion."))
        if not isinstance(providers, dict):
            # Keep inspecting supported fields to return a bounded, keyed set of
            # diagnostics; malformed provider mappings are never normalized.
            providers = {}
        for provider_id, provider in providers.items():
            if not isinstance(provider_id, str) or not isinstance(provider, dict):
                violations.append(_violation("provider_invalid", "Each provider entry must be an object."))
                continue
            options = provider.get("options", {})
            if not isinstance(options, dict):
                violations.append(_violation("provider_options_invalid", "Provider options must be an object."))
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
            if not isinstance(auth, list) or any(not _valid_v2_auth_entry(entry) for entry in auth):
                violations.append(_violation("auth_invalid", "auth.json must contain supported credential entries."))
            elif not any(entry["active"] and entry["value"]["key"].strip() for entry in auth):
                violations.append(_violation("auth_missing", "auth.json does not contain active provider credentials."))
        else:
            violations.append(_violation("auth_missing", "Add provider credentials using the v2 auth file."))
        # MCP and skills are deliberately not validated by provider setup.
        return violations

    async def list_models(self, user_id: str, config_id: str | None = None) -> list[str]:
        return await self.runtime.list_models(user_id, config_id)

    async def list_candidate_models(self, user_id: str, config: dict, auth: list | None) -> list[str]:
        return await self.runtime.list_candidate_models(user_id, config, auth)

    async def verify_candidate_model(self, user_id: str, config: dict, auth: list | None, model: str) -> dict:
        try:
            return await asyncio.wait_for(
                self.runtime.verify_candidate_model(user_id, config, auth, model),
                timeout=self.verify_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_TIMEOUT",
                    "message_key": "errors.provider.verification_timeout", "params": {"provider": "opencode"}}}

    async def verify_model(self, user_id: str, model: str, config_id: str | None = None) -> dict:
        try:
            result = await asyncio.wait_for(
                self.runtime.verify_model(user_id, model, config_id), timeout=self.verify_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_TIMEOUT",
                    "message_key": "errors.provider.verification_timeout", "params": {"provider": "opencode"}}}
        except Exception as exc:
            return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_FAILED",
                    "message_key": "errors.provider.verification_failed", "params": {"reason": type(exc).__name__}}}
        # The activity result is already a safe DTO (assertion + latency, or a
        # keyed error); it passes through unchanged.
        if isinstance(result, dict) and (result.get("ok") or isinstance(result.get("error"), dict)):
            return result
        return {"ok": False, "error": {"code": "PROVIDER_VERIFICATION_FAILED",
                "message_key": "errors.provider.verification_failed", "params": {}}}


def _valid_v2_auth_entry(entry) -> bool:
    return (isinstance(entry, dict) and set(entry) == {"id", "integrationID", "label", "active", "value"}
            and all(isinstance(entry.get(key), str) and bool(entry[key])
                    for key in ("id", "integrationID", "label"))
            and isinstance(entry.get("active"), bool)
            and isinstance(entry.get("value"), dict)
            and set(entry["value"]) == {"type", "key"}
            and entry["value"].get("type") == "api"
            and all(isinstance(entry["value"].get(key), str) and bool(entry["value"][key])
                    for key in ("type", "key")))


def _violation(code: str, message: str) -> dict:
    return {"code": code, "message_key": f"errors.provider.{code}", "params": {}}
