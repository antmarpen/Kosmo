import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
// Initializes i18next (nested en/es catalogs, localStorage persistence).
import "@/i18n";
import App from "@/app/App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
