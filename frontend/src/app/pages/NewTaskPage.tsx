import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

export function NewTaskPage() {
  const { t } = useTranslation();
  return <section className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-5 py-9 sm:px-8 sm:py-12">
    <div><h1 className="text-2xl font-semibold tracking-tight text-balance">{t("tasks.new.title")}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{t("tasks.new.description")}</p></div>
    <div className="mt-8 flex min-h-64 flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-card/50 px-6 py-10 text-center sm:min-h-80">
      <div aria-hidden="true" className="mb-4 flex size-11 items-center justify-center rounded-md bg-accent text-xl text-accent-foreground">＋</div>
      <h2 className="text-base font-medium">{t("tasks.new.formTitle")}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">{t("tasks.new.formDescription")}</p>
      <Button type="button" disabled className="mt-6">{t("tasks.new.submit")}</Button>
    </div>
  </section>;
}
