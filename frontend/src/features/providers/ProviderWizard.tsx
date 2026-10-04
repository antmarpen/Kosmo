import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { KosmoErrorAlert, type KosmoError } from "@/components/KosmoErrorAlert";
import { useCurrentUser } from "@/features/auth/useCurrentUser";
import { toKosmoError } from "./apiError";
import { canProceedWithProvider, providerCapabilities, type ProviderAuthMethod, type ProviderType } from "./capabilities";
import { parseConfigObject, readProviderAuthFile, readProviderFile, serializeProviderConfig, type AuthCredential, type Config, type ProviderFileFailure } from "./providerFile";
import { ProviderIcon } from "./providerIcons";

type Violation = { message_key: string; params?: Record<string, unknown> };
type AuthFile = { filename: string; value: AuthCredential[] };
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
  /** Seconds of validity left for the returned proof, when one was issued. */
  proof_expires_in_seconds?: number;
  error?: KosmoError;
};

/**
 * A verified connection for the CURRENT config+auth pair: the usable proof
 * (a redeemable verification id) plus the instant its validity ends. Cleared
 * on any config/auth change and when the proof window closes.
 */
type VerifiedConnection = { model: string; latencyMs: number; verificationId: string; expiresAt: number };

const PROOF_EXPIRED_ERROR: KosmoError = {
  code: "PROVIDER_PROOF_EXPIRED",
  message_key: "providers.wizard.proofExpired",
};
const SAVED_UNVERIFIED_ERROR: KosmoError = {
  code: "PROVIDER_SAVED_UNVERIFIED",
  message_key: "providers.wizard.savedUnverified",
};

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
    case "invalid_auth":
      return { code: "PROVIDER_AUTH_INVALID", message_key: "providers.wizard.invalidAuth", params };
    case "unsupported_auth":
      return { code: "PROVIDER_AUTH_UNSUPPORTED", message_key: "providers.wizard.unsupportedAuth", params };
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

/**
 * A stored instance being reconfigured: the wizard edits exactly this id
 * (type locked, name/scope prefilled) and never receives file contents.
 */
export type EditableProviderConfig = {
  id: string;
  name: string;
  provider_type: string;
  visibility: string;
  group_id: string | null;
  auth_present: boolean;
  format?: string;
};

export function ProviderWizard({ onCancel, onComplete, editConfig }: {
  onCancel: () => void;
  onComplete: () => void;
  editConfig?: EditableProviderConfig;
}) {
  const { t } = useTranslation();
  const { capabilities, user } = useCurrentUser();
  // Edit mode reopens the onboarding flow for one stored instance: the type
  // step is locked away, and name/scope start from the stored values.
  const editMode = editConfig !== undefined;
  const [step, setStep] = useState(0);
  const [provider, setProvider] = useState<ProviderType | null>(
    editConfig ? (editConfig.provider_type as ProviderType) : null);
  const [authMethod, setAuthMethod] = useState<ProviderAuthMethod | null>(null);
  const [name, setName] = useState(editConfig?.name ?? "");
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
  const [proofExpired, setProofExpired] = useState(false);
  const [savedUnverified, setSavedUnverified] = useState(false);
  const [visibility, setVisibility] = useState(editConfig?.visibility ?? "personal");
  const [groupId, setGroupId] = useState(editConfig?.group_id ?? "");
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
  const stepList: WizardStep[] = editMode
    ? ["data", "connection", "save"]
    : provider && authMethods.length > 1
      ? ["type", "method", "data", "connection", "save"]
      : ["type", "data", "connection", "save"];
  const currentStep: WizardStep = stepList[Math.min(step, stepList.length - 1)];
  // In edit mode the stored encrypted files are kept unless the user uploads
  // replacements on the data step; replacement is known before continuing.
  const filesReplaced = editMode && (selectedConfigFile !== null || auth !== null);
  const conversionRequired = editMode && editConfig.format !== "v2"
    && (selectedConfigFile === null || (editConfig.auth_present && auth === null));

  // The proof is time-bound server-side: when the remaining validity the API
  // reported runs out, the local verified state expires and a retest is
  // required before anything can be saved.
  useEffect(() => {
    if (!verified) return;
    const remaining = verified.expiresAt - Date.now();
    if (remaining <= 0) {
      setVerified(null);
      setProofExpired(true);
      return;
    }
    const timer = window.setTimeout(() => {
      setVerified(null);
      setProofExpired(true);
    }, remaining);
    return () => window.clearTimeout(timer);
  }, [verified]);

  /** Drops discovered models and the connection-test result whenever the config or auth input changes. */
  function invalidateDiscovery() {
    requestSeq.current += 1;
    setBusy(false);
    setModels([]);
    setSelectedModel("");
    setVerified(null);
    setProofExpired(false);
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
    const result = await readProviderAuthFile(file);
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
    // In edit mode the stored configuration may be kept: only a replaced file
    // is parsed and resent, and the stored one is referenced by id instead.
    const configReplaced = !editMode || selectedConfigFile !== null;
    const parsed = configReplaced ? parseConfigObject(configText) : null;
    if (configReplaced && !parsed) {
      setViolations([{ message_key: "providers.wizard.invalidJson", params: { filename: fileName } }]);
      return;
    }
    const requestId = ++requestSeq.current;
    setBusy(true); setError(null); setViolations([]);
    try {
      // Edit mode names the targeted instance and sends ONLY the replaced
      // files: the backend overlays them on the stored encrypted pair, so the
      // verification attests exactly the configuration that will be saved.
      const body = editConfig
        ? { config_id: editConfig.id, ...(parsed ? { config: parsed } : {}), ...(auth ? { auth: auth.value } : {}) }
        : { config: parsed as Config, ...(auth ? { auth: auth.value } : {}) };
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
      setError(toKosmoError(cause));
    } finally {
      if (requestId === requestSeq.current) setBusy(false);
    }
  }

  async function runVerification() {
    if (!selectedModel || (!config && !auth)) return;
    const requestId = ++requestSeq.current;
    setBusy(true); setError(null);
    try {
      // Edit mode attests the effective pair: the targeted instance id plus
      // only the replaced files; the stored ones are overlaid server-side.
      const body = editConfig
        ? { config_id: editConfig.id, ...(config ? { config } : {}), ...(auth ? { auth: auth.value } : {}), model: selectedModel }
        : { config: config as Config, ...(auth ? { auth: auth.value } : {}), model: selectedModel };
      const result = await api.POST("/providers/opencode/config/candidate/verify-model", { body });
      if (requestId !== requestSeq.current) return;
      if (result.error) throw result.error;
      const response = result.data as ModelVerification;
      if (!response.ok) {
        setError(response.error ?? { code: "PROVIDER_VERIFICATION_FAILED", message_key: "errors.provider.verification_failed" });
        return;
      }
      // Only a usable proof counts as verified: a success without a redeemable
      // verification id or without remaining validity proves nothing and must
      // be retried.
      const verificationId = typeof response.verification_id === "string" ? response.verification_id : "";
      const expiresIn = typeof response.proof_expires_in_seconds === "number"
        ? Math.floor(response.proof_expires_in_seconds) : 0;
      if (!verificationId || expiresIn <= 0) {
        setError({ code: "PROVIDER_PROOF_UNUSABLE", message_key: "providers.wizard.proofMissing" });
        return;
      }
      setProofExpired(false);
      setSavedUnverified(false);
      setVerified({
        model: selectedModel,
        latencyMs: response.latency_ms ?? 0,
        verificationId,
        expiresAt: Date.now() + expiresIn * 1000,
      });
    } catch (cause) {
      if (requestId !== requestSeq.current) return;
      setError(toKosmoError(cause));
    } finally {
      if (requestId === requestSeq.current) setBusy(false);
    }
  }

  async function commit() {
    // Creating requires the proof: a configuration tested without a
    // redeemable verification id would only be stored as unverified. An edit
    // requires it only when the stored files are being replaced; a rename or
    // scope move keeps the stored files and their recorded status.
    if (!isNameValid) return;
    if (editMode) {
      if (filesReplaced && !verified?.verificationId) return;
    } else if (!config || !verified?.verificationId) return;
    const requestId = ++requestSeq.current;
    setBusy(true); setError(null);
    try {
      const form = new FormData();
      // The update contract targets the edited instance by id: the same id
      // always comes back, and rows are never matched by scope.
      if (editConfig) form.append("config_id", editConfig.id);
      // Required friendly name (trimmed); the list shows it instead of the type.
      form.append("name", trimmedName);
      // Re-serialize the parsed object: JSONC input still uploads as strict
      // JSON. In edit mode an unreplaced config file is NOT resent: the
      // backend keeps the stored encrypted one (absent = keep).
      const configToStore = editMode && selectedConfigFile === null ? null : config;
      if (configToStore) form.append("opencode_json", new File([serializeProviderConfig(configToStore)], "opencode.json", { type: "application/json" }));
      if (auth) form.append("auth_json", new File([serializeProviderConfig(auth.value)], "auth.json", { type: "application/json" }));
      form.append("visibility", visibility);
      if (visibility === "group" && groupId) form.append("group_id", groupId);
      // Proof that the current config+auth passed the connection test. No
      // model is persisted: the model choice belongs to agents, not providers.
      if (verified?.verificationId) form.append("verification_id", verified.verificationId);
      const result = editMode
        ? await api.PATCH("/providers/opencode/config", { body: form as never })
        : await api.PUT("/providers/opencode/config", { body: form as never });
      if (requestId !== requestSeq.current) return;
      if (result.error) throw result.error;
      // The save response decides the outcome: only a backend-verified result
      // closes the wizard. When the proof was rejected (expired, consumed, or
      // mismatched), the honest unverified outcome is shown instead of plain
      // success.
      const saved = result.data as { verification_status?: string };
      if (saved.verification_status === "verified") {
        onComplete();
        return;
      }
      setVerified(null);
      setProofExpired(false);
      setSavedUnverified(true);
    } catch (cause) {
      if (requestId !== requestSeq.current) return;
      setError(toKosmoError(cause));
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
        // An edit that keeps both stored files needs no discovery or
        // connection test: go straight to the save step.
        if (editMode && !filesReplaced) { setStep(stepList.indexOf("save")); return; }
        void continueFromData();
        break;
      case "connection":
        // Progress is only possible with a successful test for the current
        // config+auth; otherwise the primary action runs the test.
        if (verified && verified.model === selectedModel) setStep(step + 1);
        else void runVerification();
        break;
      case "save":
        // After the honest unverified outcome the save already happened: the
        // primary action only closes the wizard.
        if (savedUnverified) { onComplete(); return; }
        void commit();
        break;
    }
  };
  const canNext = currentStep === "type" ? !!provider && canProceedWithProvider(provider)
      : currentStep === "method" ? !!authMethod && !busy
      : currentStep === "data" ? (editMode
          // Any replacement (either or both files) is allowed: the candidate
          // flow attests the stored pair overlaid with the replaced files.
          ? isNameValid && !busy && !conversionRequired
          : isNameValid && !!configText.trim() && !busy)
      : currentStep === "connection" ? models.length > 0 && !!selectedModel && !busy
      : savedUnverified ? !busy && isNameValid
      : !busy && isNameValid && (editMode && !filesReplaced
          ? true
          : !!verified && (visibility !== "group" || !!groupId));
  const primaryLabelKey = currentStep === "save" && savedUnverified ? "done"
      : currentStep === "save" ? "save"
      : currentStep === "connection" && !(verified && verified.model === selectedModel) ? "testAction"
      : "continue";

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
    {/* The edit* keys are pending the coordinator's catalog addition; the
        English defaults keep the UI honest until the catalogs carry them. */}
    <h1 id="wizard-title" className="mt-2 text-2xl font-semibold tracking-tight text-balance">{editMode ? t("providers.wizard.editTitle" as never, { defaultValue: "Edit provider configuration" }) : t(`providers.wizard.steps.${currentStep}` as never)}</h1>
    <p className="mt-2 text-sm leading-6 text-muted-foreground">{editMode ? t("providers.wizard.editDescription" as never, { defaultValue: "Update the name, files, or availability. Saved files are kept unless you upload replacements." }) : t(`providers.wizard.stepDescriptions.${currentStep}` as never)}</p>

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
          {editMode && <p className="text-xs text-muted-foreground">{t("providers.wizard.configKept")}</p>}
          {selectedConfigFile && <p aria-live="polite" className="text-sm">{t("providers.wizard.fileSelected", { name: selectedConfigFile })}</p>}
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("providers.wizard.authLabel")}</p>
          <p className="text-xs text-muted-foreground">{t("providers.wizard.authHint")}</p>
          {editMode && <p className="text-xs text-muted-foreground">{t("providers.wizard.authKept")}</p>}
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
        {conversionRequired && <KosmoErrorAlert error={{ code: "PROVIDER_CONVERSION_REQUIRED", message_key: "providers.wizard.conversionRequired" }} />}
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
        {proofExpired && <KosmoErrorAlert error={PROOF_EXPIRED_ERROR} />}
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
        {proofExpired && <KosmoErrorAlert error={PROOF_EXPIRED_ERROR} />}
        {savedUnverified && <KosmoErrorAlert error={SAVED_UNVERIFIED_ERROR} />}
        {error && <KosmoErrorAlert error={error} />}
        <p className="text-sm text-muted-foreground">{t("providers.wizard.commitSummary", { provider: provider ? t(`providers.types.${provider}.label`) : "", owner: user?.username ?? "" })}</p>
      </CardContent></Card>}
    </div>
    {error && currentStep !== "connection" && currentStep !== "save" && <div className="mt-5"><KosmoErrorAlert error={error} /></div>}
    <div className="mt-7 flex flex-col-reverse gap-3 border-t border-border pt-5 sm:flex-row sm:justify-between">
      <Button type="button" variant="outline" disabled={step === 0 || busy} onClick={() => { setError(null); setViolations([]); setFileError(null); setStep(step - 1); }}>{t("providers.wizard.back")}</Button>
      <Button type="button" disabled={!canNext} loading={busy} onClick={next} className="w-full sm:w-auto">{t(`providers.wizard.${primaryLabelKey}` as never)}</Button>
    </div>
  </section>;
}
