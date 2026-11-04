const fragment = window.location.hash.slice(1);
if (fragment && /^[A-Za-z0-9_:.\-]{1,512}$/.test(fragment)) {
  const form = document.getElementById("guest-order-form");
  document.getElementById("guest-token").value = fragment;
  window.history.replaceState(null, "", window.location.pathname);
  form.requestSubmit();
}
