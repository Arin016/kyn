import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { DemoDirector } from "../demo/DemoDirector";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "./styles/global.css";
import "./styles/marketing.css";

const isDirector = new URLSearchParams(location.search).get("demo") === "director";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {isDirector ? <DemoDirector /> : <App />}
  </StrictMode>,
);
