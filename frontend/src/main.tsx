import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { BootGate } from "./components/BootGate";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BootGate>
      <App />
    </BootGate>
  </StrictMode>,
);
