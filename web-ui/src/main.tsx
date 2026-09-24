import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { DemoDirector } from "../demo/DemoDirector";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles/global.css";
import "./styles/marketing.css";

const isDirector = new URLSearchParams(location.search).get("demo") === "director";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {isDirector ? <DemoDirector /> : <App />}
  </StrictMode>,
);

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`, {
      scope: import.meta.env.BASE_URL,
    });
  });
}
