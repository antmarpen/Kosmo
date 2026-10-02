import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { useCurrentUser } from "@/features/auth/useCurrentUser";
import { canProceedWithProvider, providerCapabilities, type ProviderAuthMethod, type ProviderType } from "./capabilities";
import { parseConfigObject, readProviderFile, serializeProviderConfig, type Config, type ProviderFileFailure } from "./providerFile";
import { ProviderIcon } from "./providerIcons";

type Violation = { message_key: string; params?: Record<string, unknown> };
type AuthFile = { filename: string; value: Config };
type DragZone = "config" | "auth" | null;
/** Steps of the wizard in owner-specified order; `method` only exists for providers with several auth methods. */
type WizardStep = "type" | "method" | "data" | "connection" | "save";

/** Mirrors the backend name contract: trimmed, 1..80 characters. */
const NAME_MAX_LENGTH = 80;

/** Body of the candidate verify-model endpoint (openapi-typescript types it as `unknown`). */
type ModelVerification = {
  ok: boolean;
  latency_ms?: number;
  verification_id?: string;
  error?: KosmoError;
};

/** A successful connection test for the CURRENT config+auth pair. Cleared on any config/auth change. */
type VerifiedConnection = { model: string; latencyMs: number; verificationId: string | null };

/**
 * Normalizes thrown API failures into a KosmoError. The backend emits flat
 * error bodies (`{ code, message_key, params, details }`), which openapi-fetch
 * exposes as `result.error`; pass those through so localized message keys are
 * never masked by the generic fallback.
 */
function readError(cause: unknown): KosmoError {
  const raw = cause as { error?: KosmoError; code?: string; message_key?: string; params?: Record<string, unknown> } | undefined;
  if (raw?.error) return raw.error;
  if (raw?.message_key) return { code: raw.code ?? "PROVIDER_REQUEST_FAILED", message_key: raw.message_key, params: raw.params };
  return { code: "PROVIDER_REQUEST_FAILED", message_key: "errors.generic" };
}

function fileFailureError(failure: ProviderFileFailure): KosmoError {
  const params = { filename: failure.filename };
  switch (failure.reason) {
    case "unsupported_type":
      return { code: "PROVIDER_FILE_REJECTED", message_key: "providers.wizard.wrongFileType", params };
    case "too_large":
      return { code: "PROVIDER_FILE_REJECTED", message_key: "providers.wizard.fileTooLarge", params };
    case "read_failed":
      return { code: "PROVIDER_FILE_REJECTED", message_key: "providers.wizard.fileReadFailed", params };
    case "invalid_json":
      return { code: "PROVIDER_FILE_INVALID", message_key: "providers.wizard.invalidJson", params };
  }
}

function CheckIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false" {...props}>
      <path d="M3 8.5 6.5 12 13 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const CONFIG_DROPZONE_ACCEPT = ".json,.jsonc,application/json";
const SELECT_CLASS = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50";

export function ProviderWizard({ onCancel, onComplete }: { onCancel: () => void; onComplete: () => void }) {
  const { t } = useTranslation();
  const { capabilities, user } = useCurrentUser();
  const [step, setStep] = useState(0);
  const [provider, setProvider] = useState<ProviderType | null>(null);
  const [authMethod, setAuthMethod] = useState<ProviderAuthMethod | null>(null);
  const [name, setName] = useState("");
  const [configText, setConfigText] = useState("");
  const [config, setConfig] = useState<Config | null>(null);
  const [fileName, setFileName] = useState("opencode.json");
  const [selectedConfigFile, setSelectedConfigFile] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthFile | null>(null);
  const [dragOver, setDragOver] = useState<DragZone>(null);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [fileError, setFileError] = useState<KosmoError | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [verified, setVerified] = useState<VerifiedConnection | null>(null);
  const [visibility, setVisibility] = useState("personal");
  const [groupId, setGroupId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<KosmoError | null>(null);
  // Bumped on every discovery/verification-invalidating change; in-flight
  // candidate responses compare against it and discard themselves when stale.
  const requestSeq = useRef(0);
  const managedGroups = capabilities?.groups ?? [];
  const isAdmin = capabilities?.scopes.global ?? false;
  const showScope = managedGroups.length > 0 || isAdmin;

  // The friendly name is mandatory and sent as a required multipart `name`
  // field. It starts empty on purpose: no default and never the provider type.
  const trimmedName = name.trim();
  const isNameValid = trimmedName.length >= 1 && trimmedName.length <= NAME_MAX_LENGTH;

  // The auth-method step only exists for providers offering several methods;
  // single-method providers (OpenCode today) skip it silently.
  const authMethods = provider ? providerCapabilities.find((item) => item.type === provider)?.authMethods ?? [] : [];
  const stepList: WizardStep[] = provider && authMethods.length > 1
    ? ["type", "method", "data", "connection", "save"]
    : ["type", "data", "connection", "save"];
  const currentStep: WizardStep = stepList[Math.min(step, stepList.length - 1)];

  /** Drops discovered models and the connection-test result whenever the config or auth input changes. */
  function invalidateDiscovery() {
    requestSeq.current += 1;
    setBusy(false);
    setModels([]);
    setSelectedModel("");
    setVerified(null);
    setViolations([]);
    setFileError(null);
    setError(null);
  }

  async function loadConfigFile(file: File) {
    setFileError(null);
    const result = await readProviderFile(file);
    if (!result.ok) { setFileError(fileFailureError(result.failure)); return; }
    invalidateDiscovery();
    setConfigText(result.text);
    setFileName(result.filename);
    setSelectedConfigFile(result.filename);
  }

  async function loadAuthFile(file: File) {
    setFileError(null);
    if (file.name.toLowerCase() !== "auth.json") {
      setFileError({ code: "PROVIDER_FILE_REJECTED", message_key: "providers.wizard.authNameRequired", params: { filename: file.name } });
      return;
    }
    const result = await readProviderFile(file);
    if (!result.ok) { setFileError(fileFailureError(result.failure)); return; }
    invalidateDiscovery();
    setAuth({ filename: result.filename, value: result.value });
  }

  function removeAuth() {
    invalidateDiscovery();
    setAuth(null);
  }

  function chooseProvider(type: ProviderType) {
    setProvider(type);
    setAuthMethod(null);
  }

  async function continueFromData() {
    if (!isNameValid) {
      setError({ code: "PROVIDER_NAME_INVALID", message_key: "errors.provider.name_invalid" });
      return;
    }
    const parsed = parseConfigObject(configText);
    if (!parsed) {
      setViolations([{ message_key: "providers.wizard.invalidJson", params: { filename: fileName } }]);
      return;
    }
    const requestId = ++requestSeq.current;
    setBusy(true); setError(null); setViolations([]);
    try {
      const body: { config: Config; auth?: Config } = auth ? { config: parsed, auth: auth.value } : { config: parsed };
      const result = await api.POST("/providers/opencode/config/candidate/validate", { body });
      if (requestId !== requestSeq.current) return;
      if (result.error) throw result.error;
      const response = result.data as { valid: boolean; violations: Violation[] };
      if (!response.valid) { setViolations(response.violations ?? []); return; }
      const modelResult = await api.POST("/providers/opencode/config/candidate/models", { body });
      if (requestId !== requestSeq.current) return;
      if (modelResult.error) throw modelResult.error;
      const modelResponse = modelResult.data as { valid: boolean; violations: Violation[]; models: string[] };
      if (!modelResponse.valid) { setViolations(modelResponse.violations ?? []); return; }
      setConfig(parsed);
      setModels(modelResponse.models ?? []);
      setSelectedModel(modelResponse.models?.[0] ?? "");
      setStep((current) => current + 1);
    } catch (cause) {
      if (requestId !== requestSeq.current) return;
      setError(readError(cause));
    } finally {
      if (requestId === requestSeq.current) setBusy(false);
    }
  }

  async function runVerification() {
    if (!config || !selectedModel) return;
    const requestId = ++requestSeq.current;
    setBusy(true); setError(null);
    try {
      const body: { config: Config; auth?: Config; model: string } = auth
        ? { config, auth: auth.value, model: selectedModel }
        : { config, model: selectedModel };
      const result = await api.POST("/providers/opencode/config/candidate/verify-model", { body });
      if (requestId !== requestSeq.current) return;
      if (result.error) throw result.error;
      const response = result.data as ModelVerification;
      if (!response.ok) {
        setError(response.error ?? { code: "PROVIDER_VERIFICATION_FAILED", message_key: "errors.provider.verification_failed" });
        return;
      }
      setVerified({ model: selectedModel, latencyMs: response.latency_ms ?? 0, verificationId: response.verification_id ?? null });
    } catch (cause) {
      if (requestId !== requestSeq.current) return;
      setError(readError(cause));
    } finally {
      if (requestId === requestSeq.current) setBusy(false);
    }
  }

  async function commit() {
    if (!config || !verified || !isNameValid) return;
    const requestId = ++requestSeq.current;
    setBusy(true); setError(null);
    try {
      const form = new FormData();
      // Required friendly name (trimmed); the list shows it instead of the type.
      form.append("name", trimmedName);
      // Re-serialize the parsed object: JSONC input still uploads as strict JSON.
      form.append("opencode_json", new File([serializeProviderConfig(config)], "opencode.json", { type: "application/json" }));
      if (auth) form.append("auth_json", new File([serializeProviderConfig(auth.value)], "auth.json", { type: "application/json" }));
      form.append("visibility", visibility);
      if (visibility === "group" && groupId) form.append("group_id", groupId);
      // Proof that the current config+auth passed the connection test. No
      // model is persisted: the model choice belongs to agents, not providers.
      if (verified.verificationId) form.append("verification_id", verified.verificationId);
      const result = await api.PUT("/providers/opencode/config", { body: form as never });
      if (requestId !== requestSeq.current) return;
      if (result.error) throw result.error;
      onComplete();
    } catch (cause) {
      if (requestId !== requestSeq.current) return;
      setError(readError(cause));
    } finally {
      if (requestId === requestSeq.current) setBusy(false);
    }
  }

  const next = () => {
    switch (currentStep) {
      case "type":
        if (provider && canProceedWithProvider(provider)) setStep(step + 1);
        break;
      case "method":
        if (authMethod) setStep(step + 1);
        break;
      case "data":
        void continueFromData();
        break;
      case "connection":
        // Progress is only possible with a successful test for the current
        // config+auth; otherwise the primary action runs the test.
        if (verified && verified.model === selectedModel) setStep(step + 1);
        else void runVerification();
        break;
      case "save":
        void commit();
        break;
    }
  };
  const canNext = currentStep === "type" ? !!provider && canProceedWithProvider(provider)
      : currentStep === "method" ? !!authMethod && !busy
      : currentStep === "data" ? isNameValid && !!configText.trim() && !busy
      : currentStep === "connection" ? models.length > 0 && !!selectedModel && !busy
      : !busy && isNameValid && !!verified && (visibility !== "group" || !!groupId);
  const primaryLabelKey = currentStep === "save" ? "save"
      : currentStep === "connection" && !(verified && verified.model === selectedModel) ? "testAction"
      : "continue";
  const busyLabelKey = currentStep === "connection" ? "testing" : "working";

  const configDropzoneHandlers = {
    onDragOver: (event: React.DragEvent<HTMLLabelElement>) => { event.preventDefault(); setDragOver("config"); },
    onDragLeave: () => setDragOver((zone) => (zone === "config" ? null : zone)),
    onDrop: (event: React.DragEvent<HTMLLabelElement>) => {
      event.preventDefault(); setDragOver(null);
      const file = event.dataTransfer.files?.[0];
      if (file) void loadConfigFile(file);
    },
  };
  const authDropzoneHandlers = {
    onDragOver: (event: React.DragEvent<HTMLLabelElement>) => { event.preventDefault(); setDragOver("auth"); },
    onDragLeave: () => setDragOver((zone) => (zone === "auth" ? null : zone)),
    onDrop: (event: React.DragEvent<HTMLLabelElement>) => {
      event.preventDefault(); setDragOver(null);
      const file = event.dataTransfer.files?.[0];
      if (file) void loadAuthFile(file);
    },
  };
  const dropzoneClassName = (zone: Exclude<DragZone, null>) =>
    `flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed px-4 py-7 text-center transition-colors has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50 ${dragOver === zone ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"}`;

  const verifiedPanel = () => verified && (
    <div role="status" className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
      <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary" />
      <div className="min-w-0 text-sm">
        <p>{t("providers.wizard.verifiedWith", { model: verified.model, latency: verified.latencyMs })}</p>
        {selectedModel !== verified.model && (
          <p className="mt-1 text-xs text-muted-foreground">{t("providers.wizard.verifiedOtherSelected", { model: selectedModel })}</p>
        )}
      </div>
    </div>
  );

  return <section aria-labelledby="wizard-title" className="mx-auto w-full max-w-4xl flex-1 px-5 py-7 sm:px-8 sm:py-10">
    <button type="button" onClick={onCancel} className="mb-5 text-sm text-muted-foreground hover:text-foreground">{t("providers.wizard.cancel")}</button>
    <div className="mb-7 flex items-center gap-2" aria-label={t("providers.wizard.progress", { current: step + 1, total: stepList.length })}>
      {stepList.map((key, index) => <div key={key} className={`h-1.5 flex-1 rounded-full ${index <= step ? "bg-primary" : "bg-muted"}`} />)}
    </div>
    <p className="text-sm font-medium text-primary">{t("providers.wizard.step", { current: step + 1, total: stepList.length })}</p>
    <h1 id="wizard-title" className="mt-2 text-2xl font-semibold tracking-tight text-balance">{t(`providers.wizard.steps.${currentStep}` as never)}</h1>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">{t(`providers.wizard.stepDescriptions.${currentStep}` as never)}</p>

    <div className="mt-7">
      {currentStep === "type" && <div className="grid gap-3 sm:grid-cols-3">{providerCapabilities.map((item) => <button key={item.type} type="button" disabled={!item.available} aria-pressed={provider === item.type} onClick={() => chooseProvider(item.type)} className={`min-h-36 rounded-lg border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-65 ${provider === item.type ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/50"}`}>
        <span className="flex items-start justify-between gap-2"><span className="flex items-center gap-2 font-semibold"><ProviderIcon type={item.type} size={20} className="shrink-0" />{t(item.label as never)}</span>{!item.available && <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{t("providers.wizard.comingSoon")}</span>}</span>
        <span className="mt-3 block text-sm leading-5 text-muted-foreground">{t(item.description as never)}</span>
      </button>)}</div>}
      {currentStep === "method" && <div className="grid gap-3 sm:grid-cols-2">{authMethods.map((method) => <button key={method} type="button" aria-pressed={authMethod === method} onClick={() => setAuthMethod(method)} className={`min-h-36 rounded-lg border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 ${authMethod === method ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/50"}`}>
        <span className="block font-semibold">{t(`providers.wizard.methods.${method}.label` as never)}</span>
        <span className="mt-3 block text-sm leading-5 text-muted-foreground">{t(`providers.wizard.methods.${method}.description` as never)}</span>
      </button>)}</div>}
      {currentStep === "data" && <Card><CardHeader><CardTitle>{t("providers.wizard.configTitle")}</CardTitle><CardDescription>{t("providers.wizard.configDescription")}</CardDescription></CardHeader><CardContent className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="provider-name" className="block text-sm font-medium">
            {t("providers.wizard.nameLabel")}
            <span aria-hidden="true" className="text-destructive"> *</span>
            <span className="sr-only">{t("providers.wizard.nameRequired")}</span>
          </label>
          <Input
            id="provider-name"
            type="text"
            value={name}
            maxLength={NAME_MAX_LENGTH}
            required
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">{t("providers.wizard.nameHint")}</p>
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("providers.wizard.fileLabel")}</p>
          <label htmlFor="provider-file" aria-describedby="provider-file-hint" {...configDropzoneHandlers} className={dropzoneClassName("config")}>
            <input
              id="provider-file"
              type="file"
              accept={CONFIG_DROPZONE_ACCEPT}
              className="sr-only"
              onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void loadConfigFile(file); }}
            />
            <span className="text-sm font-medium">{t("providers.wizard.dropzoneLabel")}</span>
          </label>
          <p id="provider-file-hint" className="text-xs text-muted-foreground">{t("providers.wizard.dropzoneHint")}</p>
          {selectedConfigFile && <p aria-live="polite" className="text-sm">{t("providers.wizard.fileSelected", { name: selectedConfigFile })}</p>}
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("providers.wizard.authLabel")}</p>
          <p className="text-xs text-muted-foreground">{t("providers.wizard.authHint")}</p>
          {<label htmlFor="provider-auth-file" {...authDropzoneHandlers} className={dropzoneClassName("auth")}>
            <input
              id="provider-auth-file"
              type="file"
              accept=".json,application/json"
              className="sr-only"
              onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void loadAuthFile(file); }}
            />
            <span className="text-sm font-medium">{t("providers.wizard.authDropzone")}</span>
          </label>}
          {auth && <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/30 px-3 py-2">
            <span aria-live="polite" className="min-w-0 truncate text-sm">{t("providers.wizard.authSelected", { name: auth.filename })}</span>
            <Button type="button" variant="outline" size="xs" onClick={removeAuth}>{t("providers.wizard.authRemove")}</Button>
          </div>}
        </div>
        {fileError && <KosmoErrorAlert error={fileError} />}
        {violations.length > 0 && <KosmoErrorAlert error={{ code: "PROVIDER_CONFIG_INVALID", message_key: "errors.provider.config_invalid", details: violations }} />}
      </CardContent></Card>}
      {currentStep === "connection" && <Card><CardHeader><CardTitle>{t("providers.wizard.connectionTitle")}</CardTitle><CardDescription>{t("providers.wizard.connectionDescription")}</CardDescription></CardHeader><CardContent className="space-y-4">
        {models.length > 0 ? <div className="space-y-2">
          <label htmlFor="provider-model" className="block text-sm font-medium">{t("providers.wizard.modelsTitle")}</label>
          <select id="provider-model" value={selectedModel} disabled={busy} onChange={(event) => setSelectedModel(event.target.value)} className={SELECT_CLASS}>
            {models.map((model) => <option key={model} value={model}>{model}</option>)}
          </select>
        </div> : <p className="rounded-md bg-muted/60 px-3 py-3 text-sm">{t("providers.wizard.noModels")}</p>}
        {verifiedPanel()}
        {error && <KosmoErrorAlert error={error} />}
      </CardContent></Card>}
      {currentStep === "save" && <Card><CardHeader><CardTitle>{t("providers.wizard.scopeTitle")}</CardTitle><CardDescription>{t("providers.wizard.scopeDescription")}</CardDescription></CardHeader><CardContent className="space-y-4">
        {showScope ? <fieldset className="space-y-2"><legend className="mb-2 text-sm font-medium">{t("providers.wizard.visibilityLabel")}</legend><label className="flex min-h-11 items-center gap-3 rounded-md border border-border px-3 py-2"><input type="radio" name="visibility" checked={visibility === "personal"} onChange={() => setVisibility("personal")} className="accent-primary"/><span className="text-sm">{t("providers.wizard.personal")}</span></label>
          {managedGroups.length > 0 && <label className="flex min-h-11 items-center gap-3 rounded-md border border-border px-3 py-2"><input type="radio" name="visibility" checked={visibility === "group"} onChange={() => setVisibility("group")} className="accent-primary"/><span className="text-sm">{t("providers.wizard.group")}</span></label>}
          {managedGroups.length > 0 && visibility === "group" && <div><label htmlFor="provider-group" className="mb-2 block text-sm font-medium">{t("providers.wizard.groupLabel")}</label><select id="provider-group" value={groupId} onChange={event => setGroupId(event.target.value)} className={SELECT_CLASS}><option value="">{t("providers.wizard.chooseGroup")}</option>{managedGroups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></div>}
          {isAdmin && <label className="flex min-h-11 items-center gap-3 rounded-md border border-border px-3 py-2"><input type="radio" name="visibility" checked={visibility === "global"} onChange={() => setVisibility("global")} className="accent-primary"/><span className="text-sm">{t("providers.wizard.global")}</span></label>}
        </fieldset> : <p className="rounded-md bg-muted/60 px-4 py-3 text-sm leading-6">{t("providers.wizard.personalNotice")}</p>}
        {verified && <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
          <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary" />
          <p className="min-w-0 text-sm">{t("providers.wizard.verifiedScopeNote", { model: verified.model })}</p>
        </div>}
        {error && <KosmoErrorAlert error={error} />}
        <p className="text-sm text-muted-foreground">{t("providers.wizard.commitSummary", { provider: provider ? t(`providers.types.${provider}.label`) : "", owner: user?.username ?? "" })}</p>
      </CardContent></Card>}
    </div>
    {error && currentStep !== "connection" && currentStep !== "save" && <div className="mt-5"><KosmoErrorAlert error={error} /></div>}
    <div className="mt-7 flex flex-col-reverse gap-3 border-t border-border pt-5 sm:flex-row sm:justify-between">
      <Button type="button" variant="outline" disabled={step === 0 || busy} onClick={() => { setError(null); setViolations([]); setFileError(null); setStep(step - 1); }}>{t("providers.wizard.back")}</Button>
      <Button type="button" disabled={!canNext} onClick={next} className="w-full sm:w-auto">{busy ? t(`providers.wizard.${busyLabelKey}`) : t(`providers.wizard.${primaryLabelKey}`)}</Button>
    </div>
  </section>;
}
