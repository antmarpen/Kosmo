import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/auth";

type ProviderConfig = { id: string; name: string; provider_type: string; visibility: string; verification_status: string; auth_present: boolean };
type Props = { runtime: string; model: string; onChange: (runtime: string, model: string) => void };
const SELECT_CLASS = "w-full min-w-0 rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring";

export function ProviderModelSelect({ runtime, model, onChange }: Props) {
  const { t } = useTranslation();
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [empty, setEmpty] = useState(false);
  const sequence = useRef(0);

  useEffect(() => {
    let active = true;
    void api.GET("/providers/opencode/config").then((result) => {
      if (result.error || !result.data) throw new Error("Provider list failed");
      if (active) setConfigs(result.data as ProviderConfig[]);
    }).catch(() => { if (active) setListError(true); }).finally(() => { if (active) setListLoading(false); });
    return () => { active = false; };
  }, []);

  const matching = configs.filter((config) => config.provider_type === runtime);
  useEffect(() => {
    const seq = ++sequence.current;
    setModels([]); setError(false); setEmpty(false);
    if (matching.length !== 1 || runtime !== "opencode") { setLoading(false); return; }
    setLoading(true);
    void api.POST("/providers/opencode/config/verify", { body: { config_id: matching[0].id } }).then((result) => {
      if (seq !== sequence.current) return;
      if (result.error || !result.data) throw new Error("Model discovery failed");
      const response = result.data as { valid?: boolean; models?: string[] };
      if (!response.valid) { setError(true); return; }
      setModels(response.models ?? []);
      setEmpty((response.models ?? []).length === 0);
    }).catch(() => { if (seq === sequence.current) setError(true); }).finally(() => { if (seq === sequence.current) setLoading(false); });
    return () => { sequence.current += 1; };
  }, [runtime, matching.length, matching[0]?.id]);

  const types = [...new Set<string>(configs.map(({ provider_type }) => provider_type).filter((type) => type === "opencode"))];
  const multiple = matching.length > 1;
  return <div className="grid min-w-0 gap-3">
    <label className="grid min-w-0 gap-1.5 text-sm font-medium">{t("editor.provider" as never)}
      <select aria-label={t("editor.provider" as never)} className={SELECT_CLASS} value={runtime} disabled={listLoading || listError} onChange={(event) => onChange(event.target.value, "")}>
        {runtime && !types.includes(runtime) && <option value={runtime}>{runtime}</option>}
        <option value="">{t("editor.selectProvider" as never)}</option>
        {types.map((type) => <option key={type} value={type}>{type}</option>)}
      </select>
    </label>
    {listError && <p role="alert" className="text-sm text-destructive">{t("editor.providersLoadError" as never)}</p>}
    <label className="grid min-w-0 gap-1.5 text-sm font-medium">{t("editor.model" as never)}
      <select aria-label={t("editor.model" as never)} className={SELECT_CLASS} value={model} disabled={listLoading || loading || multiple || error || empty || matching.length !== 1} onChange={(event) => onChange(runtime, event.target.value)}>
        <option value="">{t("editor.selectModel" as never)}</option>
        {model && !models.includes(model) && <option value={model}>{model}</option>}
        {models.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </label>
    {multiple && <p className="text-sm text-muted-foreground">{t("editor.multipleProviderConfigs" as never)}</p>}
    {loading && <p role="status" className="text-sm text-muted-foreground">{t("editor.loadingModels" as never)}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{t("editor.modelsLoadError" as never)}</p>}
    {empty && <p className="text-sm text-muted-foreground">{t("editor.noModels" as never)}</p>}
  </div>;
}
