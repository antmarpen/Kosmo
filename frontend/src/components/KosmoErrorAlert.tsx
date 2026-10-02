import { useTranslation } from "react-i18next";

export type KosmoErrorDetail = { message_key: string; params?: Record<string, unknown> };
export type KosmoError = {
  code: string;
  message_key: string;
  params?: Record<string, unknown>;
  details?: KosmoErrorDetail[];
};

export function KosmoErrorAlert({ error }: { error: KosmoError }) {
  const { t, i18n } = useTranslation();
  const translate = (key: string, params?: Record<string, unknown>) =>
    String(i18n.exists(key) ? t(key as never, params as never) : t("errors.generic" as never));

  return (
    <div role="alert" className="rounded-md border border-destructive/50 bg-destructive/5 p-4 text-sm text-destructive">
      <p>{translate(error.message_key, error.params)}</p>
      {error.details?.length ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {error.details.map((detail, index) => <li key={`${detail.message_key}-${index}`}>{translate(detail.message_key, detail.params)}</li>)}
        </ul>
      ) : null}
    </div>
  );
}
