for (const form of document.querySelectorAll("form[data-pending]")) {
  form.addEventListener("submit", (event) => {
    if (form.getAttribute("aria-busy") === "true") {
      event.preventDefault();
      return;
    }
    form.setAttribute("aria-busy", "true");
    const status = form.querySelector("[data-form-status]");
    if (status) status.textContent = form.dataset.pending;
  });
  window.addEventListener("pageshow", () => {
    form.removeAttribute("aria-busy");
    const status = form.querySelector("[data-form-status]");
    if (status) status.textContent = "";
  });
}
