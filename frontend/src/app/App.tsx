import { useEffect } from "react";
import i18next from "i18next";
import { BrowserRouter } from "react-router";

import { AppRoutes } from "./router";
import { AuthProvider } from "@/features/auth/AuthProvider";

/** Keeps <html lang> in sync with the active language (accessibility). */
function useDocumentLanguage() {
  useEffect(() => {
    const apply = () => {
      document.documentElement.lang = i18next.language;
    };
    apply();
    i18next.on("languageChanged", apply);
    return () => {
      i18next.off("languageChanged", apply);
    };
  }, []);
}

export default function App() {
  useDocumentLanguage();

  return (
    <BrowserRouter>
      <AuthProvider><AppRoutes /></AuthProvider>
    </BrowserRouter>
  );
}
