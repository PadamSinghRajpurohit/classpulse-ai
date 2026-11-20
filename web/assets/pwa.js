(() => {
  "use strict";

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
        // The app remains usable online if the browser disables service workers.
      });
    }, { once: true });
  }

  const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  if (standalone) return;

  const installButton = document.createElement("button");
  installButton.type = "button";
  installButton.className = "button button-quiet pwa-install hidden";
  installButton.textContent = "Add to phone";
  installButton.setAttribute("aria-label", "Add the ClassPulse web app to this device");

  const container = document.querySelector(".topbar-right");
  if (!container) return;
  container.prepend(installButton);
  const isAppleTouch = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  // iOS Safari and several other browsers do not implement beforeinstallprompt.
  // Keep a visible help action there instead of silently hiding installation.
  if (isAppleTouch || !("onbeforeinstallprompt" in window)) {
    installButton.classList.remove("hidden");
  }

  let installPrompt = null;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    installButton.classList.remove("hidden");
  });

  installButton.addEventListener("click", async () => {
    if (!installPrompt) {
      const instructions = isAppleTouch
        ? "To add ClassPulse on iPhone or iPad, open the Share menu and choose Add to Home Screen. This creates a browser-based web app; it does not download an APK."
        : "Open your browser menu and choose Install app or Add to Home screen. This adds the browser-based ClassPulse web app; it does not download an APK.";
      window.alert(instructions);
      return;
    }
    installPrompt.prompt();
    await installPrompt.userChoice.catch(() => null);
    installPrompt = null;
    installButton.classList.add("hidden");
  });

  window.addEventListener("appinstalled", () => installButton.classList.add("hidden"));
})();
