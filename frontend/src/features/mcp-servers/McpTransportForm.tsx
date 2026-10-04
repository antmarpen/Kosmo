import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { RowActionButton } from "@/components/RowActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { CatalogField, CatalogTextArea } from "@/features/catalogs/components/CatalogField";
import { cn } from "@/lib/utils";

import {
  addEntryDraft,
  removeEntryDraft,
  switchTransport,
  transportHasContent,
  updateEntryDraft,
  type McpTransportType,
  type TransportDraft,
  type TransportEntryDraft,
  type TransportEntryErrorCode,
  type TransportErrors,
} from "./transportState";

/**
 * WP-14 — bounded transport authoring block for the MCP catalog form.
 *
 * A discriminated stdio/http choice with the fields each transport needs, and
 * named env/header entries with an explicit secret classification. Stored
 * secrets hydrate as an empty masked input plus a `Set`/`Not set` presence
 * marker: a blank value means "keep the stored value" and typing means
 * "replace", so the server's keep/replace/remove contract is expressed
 * directly by the interaction. Switching transport kind asks for confirmation
 * before destroying incompatible fields, and always resets them fully — the
 * submitted collection is the exact desired set for the chosen kind.
 *
 * State is owned by the consuming form (`transport`/`onChange`) so the page
 * builds and validates the request body in one place; this component renders
 * and edits, it never submits.
 */
export function McpTransportForm({
  transport,
  onChange,
  errors = null,
  saving = false,
}: {
  transport: TransportDraft;
  onChange: (next: TransportDraft) => void;
  /** Client-side validation failures from the last submit attempt. */
  errors?: TransportErrors | null;
  saving?: boolean;
}) {
  const { t } = useTranslation();
  const idPrefix = useId();
  const [pendingType, setPendingType] = useState<McpTransportType | null>(null);
  const isStdio = transport.type === "stdio";

  function requestType(next: McpTransportType) {
    if (next === transport.type) return;
    // Authored fields are destructively discarded on a kind switch; anything
    // typed so far earns an explicit confirmation (WP-14 risk note).
    if (transportHasContent(transport)) setPendingType(next);
    else onChange(switchTransport(transport, next));
  }

  const transportOption = (value: McpTransportType, title: string, hint: string) => (
    <label
      className={cn(
        "flex min-h-11 cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-2",
      )}
    >
      <input
        type="radio"
        name={`${idPrefix}-transport-type`}
        value={value}
        aria-label={title}
        checked={transport.type === value}
        onChange={() => requestType(value)}
        disabled={saving}
        className="mt-0.5 accent-primary"
      />
      <span className="grid gap-0.5">
        <span className="text-sm">{title}</span>
        <span className="text-xs leading-5 text-muted-foreground">{hint}</span>
      </span>
    </label>
  );

  const entryNameAria = isStdio
    ? t("mcps.form.entries.nameEnv")
    : t("mcps.form.entries.nameHeader");

  function update(entryId: string, patch: Partial<Pick<TransportEntryDraft, "name" | "secret" | "value">>) {
    onChange(updateEntryDraft(transport, entryId, patch));
  }

  const entryErrorText = (code: TransportEntryErrorCode) =>
    code === "name_invalid"
      ? t("mcps.form.errors.nameInvalid")
      : code === "name_duplicate"
        ? t("mcps.form.errors.nameDuplicate")
        : t("mcps.form.errors.valueRequired");

  return (
    <div className="grid min-w-0 gap-6">
      <div role="radiogroup" aria-label={t("mcps.form.transport")} className="grid gap-2">
        <span className="text-sm font-medium">{t("mcps.form.transport")}</span>
        <div className="grid gap-2 sm:grid-cols-2">
          {transportOption("stdio", t("mcps.form.type.stdio"), t("mcps.form.type.stdioHint"))}
          {transportOption("http", t("mcps.form.type.http"), t("mcps.form.type.httpHint"))}
        </div>
      </div>

      {isStdio ? (
        <>
          <CatalogField
            label={t("mcps.form.command")}
            hint={t("mcps.form.commandHint")}
            error={errors?.command ? t("mcps.form.errors.commandInvalid") : undefined}
          >
            <Input
              value={transport.command}
              onChange={(event) => onChange({ ...transport, command: event.target.value })}
              placeholder={t("mcps.form.commandPlaceholder")}
              autoComplete="off"
              spellCheck={false}
              disabled={saving}
              className="font-mono"
            />
          </CatalogField>
          <CatalogField label={t("mcps.form.args")} hint={t("mcps.form.argsHint")}>
            <CatalogTextArea
              rows={3}
              value={transport.argsText}
              onChange={(event) => onChange({ ...transport, argsText: event.target.value })}
              placeholder={t("mcps.form.argsPlaceholder")}
              spellCheck={false}
              disabled={saving}
            />
          </CatalogField>
        </>
      ) : (
        <CatalogField
          label={t("mcps.form.url")}
          hint={t("mcps.form.urlHint")}
          error={errors?.url ? t("mcps.form.errors.urlInvalid") : undefined}
        >
          <Input
            type="url"
            value={transport.url}
            onChange={(event) => onChange({ ...transport, url: event.target.value })}
            placeholder={t("mcps.form.urlPlaceholder")}
            autoComplete="off"
            spellCheck={false}
            disabled={saving}
            className="font-mono"
          />
        </CatalogField>
      )}

      <div className="grid min-w-0 gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-medium">
            {isStdio ? t("mcps.form.entries.envTitle") : t("mcps.form.entries.headersTitle")}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={saving}
            onClick={() => onChange(addEntryDraft(transport, false))}
          >
            <Icon name="add" />
            {isStdio ? t("mcps.form.entries.addEnv") : t("mcps.form.entries.addHeader")}
          </Button>
        </div>
        {errors?.keepAfterRename ? (
          <p role="alert" className="text-xs leading-5 text-destructive">
            {t("mcps.form.errors.keepAfterRename")}
          </p>
        ) : null}
        {transport.entries.length > 0 ? (
          <ul className="grid gap-3">
            {transport.entries.map((item) => (
              <EntryRow
                key={item.id}
                entry={item}
                nameAria={entryNameAria}
                errors={errors?.entries[item.id] ?? []}
                errorText={entryErrorText}
                saving={saving}
                onUpdate={(patch) => update(item.id, patch)}
                onRemove={() => onChange(removeEntryDraft(transport, item.id))}
              />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t("mcps.form.entries.empty")}</p>
        )}
      </div>

      <ConfirmDialog
        open={pendingType !== null}
        onOpenChange={(open) => {
          if (!open) setPendingType(null);
        }}
        title={t("mcps.form.switchTitle")}
        description={t("mcps.form.switchDescription", {
          type: pendingType === "http" ? t("mcps.form.type.http") : t("mcps.form.type.stdio"),
        })}
        confirmLabel={t("mcps.form.switchConfirm")}
        onConfirm={() => {
          if (pendingType) onChange(switchTransport(transport, pendingType));
          setPendingType(null);
        }}
      />
    </div>
  );
}

/**
 * One named entry row: the name, the secret classification switch, the
 * (masked when secret) value and the entry's remove action. The presence
 * marker and keep hint only render for stored secrets — they describe server
 * state the form must not pretend to display.
 */
function EntryRow({
  entry,
  nameAria,
  errors,
  errorText,
  saving,
  onUpdate,
  onRemove,
}: {
  entry: TransportEntryDraft;
  nameAria: string;
  errors: TransportEntryErrorCode[];
  errorText: (code: TransportEntryErrorCode) => string;
  saving: boolean;
  onUpdate: (patch: Partial<Pick<TransportEntryDraft, "name" | "secret" | "value">>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  // Keep applies exactly when a stored, set secret is left untouched.
  const canKeep =
    entry.existing && entry.secret && entry.existingSecret && entry.existingIsSet;
  const presence: ReactNode =
    entry.existing && entry.secret ? (
      <span
        data-slot="entry-presence"
        className="shrink-0 rounded-md border border-border px-1.5 py-0.5 text-xs text-muted-foreground"
      >
        {entry.existingIsSet ? t("mcps.form.entries.valueSet") : t("mcps.form.entries.valueNotSet")}
      </span>
    ) : null;

  return (
    <li
      data-slot="transport-entry"
      className="grid gap-2 rounded-lg border border-border p-3"
    >
      <div className="flex flex-wrap items-center gap-3">
        <Input
          aria-label={nameAria}
          value={entry.name}
          onChange={(event) => onUpdate({ name: event.target.value })}
          autoComplete="off"
          spellCheck={false}
          disabled={saving}
          className="min-w-44 flex-1 font-mono"
        />
        <label className="flex shrink-0 cursor-pointer items-center gap-2">
          <Switch
            checked={entry.secret}
            onCheckedChange={(next) => onUpdate({ secret: next })}
            disabled={saving}
          />
          <span className="text-sm">{t("mcps.form.entries.secret")}</span>
        </label>
        <RowActionButton
          icon="delete"
          label={t("mcps.form.entries.remove")}
          onClick={onRemove}
          disabled={saving}
          className="ml-auto"
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Input
          type={entry.secret ? "password" : "text"}
          aria-label={t("mcps.form.entries.value")}
          value={entry.value}
          onChange={(event) => onUpdate({ value: event.target.value })}
          // Browsers ignore `off` for password fields; new-password avoids
          // saved-credential autofill prompts on the replacement value.
          autoComplete={entry.secret ? "new-password" : "off"}
          spellCheck={false}
          disabled={saving}
          placeholder={t("mcps.form.entries.valuePlaceholder")}
          className="min-w-44 flex-1 font-mono"
        />
        {presence}
      </div>
      {canKeep && entry.value === "" ? (
        <p className="text-xs leading-5 text-muted-foreground">
          {t("mcps.form.entries.keepHint")}
        </p>
      ) : null}
      {errors.map((code) => (
        <p key={code} role="alert" className="text-xs leading-5 text-destructive">
          {errorText(code)}
        </p>
      ))}
    </li>
  );
}
