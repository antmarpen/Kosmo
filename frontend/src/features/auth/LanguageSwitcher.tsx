import { useTranslation } from "react-i18next";

import { changeLanguage, SUPPORTED_LANGUAGES, type Language } from "@/i18n";
import { cn } from "@/lib/utils";

const LANGUAGE_LABEL_KEY = {
  en: "common.languageEnglish",
  es: "common.languageSpanish",
} as const satisfies Record<Language, string>;

/**
 * Segmented EN/ES control. Each option is labeled in its own language so the
 * control reads correctly no matter which language is active. The choice is
 * persisted to localStorage by `changeLanguage` (see src/i18n).
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { t, i18n } = useTranslation();

  return (
    <div
      role="group"
      aria-label={t("common.language")}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border border-border bg-card p-0.5",
        className,
      )}
    >
      {SUPPORTED_LANGUAGES.map((language) => {
        const isActive = i18n.language.startsWith(language);
        return (
          <button
            key={language}
            type="button"
            aria-pressed={isActive}
            onClick={() => changeLanguage(language)}
            className={cn(
              "rounded-full px-2 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
              isActive
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(LANGUAGE_LABEL_KEY[language])}
          </button>
        );
      })}
    </div>
  );
}
