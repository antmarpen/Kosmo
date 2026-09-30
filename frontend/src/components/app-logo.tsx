import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/**
 * Kosmo brand mark (brass "K" tile) + wordmark. Shared by the app shell and
 * the login page (second use, per the lift-on-second-use rule).
 */
export function AppLogo({ className }: { className?: string }) {
  const { t } = useTranslation();

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        aria-hidden="true"
        className="flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-accent text-[13px] font-bold text-white select-none"
      >
        K
      </span>
      <span className="text-[15px] font-semibold tracking-tight text-foreground">
        {t("common.appName")}
      </span>
    </span>
  );
}
