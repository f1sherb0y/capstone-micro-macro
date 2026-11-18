import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import "./styles.css";

function renderFatalError(error) {
  const appRoot = document.querySelector("#app");
  if (!appRoot) return;
  const message = error?.stack || error?.message || String(error);
  appRoot.innerHTML = `<pre style="white-space:pre-wrap;padding:24px;color:#b42318;background:#fff7f5;font:14px/1.5 ui-monospace,Menlo,monospace;">${message.replace(/[<>&]/g, (char) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[char])}</pre>`;
}

window.addEventListener("error", (event) => renderFatalError(event.error || event.message));
window.addEventListener("unhandledrejection", (event) => renderFatalError(event.reason));

try {
  createApp(App).use(ElementPlus).mount("#app");
} catch (error) {
  renderFatalError(error);
}
