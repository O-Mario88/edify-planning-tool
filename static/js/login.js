(function () {
  "use strict";

  document.addEventListener("pointerdown", function () {
    document.documentElement.dataset.edifyInputModality = "pointer";
  }, { capture: true, passive: true });
  document.addEventListener("keydown", function () {
    document.documentElement.dataset.edifyInputModality = "keyboard";
  }, { capture: true });

  function initPasswordToggles() {
    document.querySelectorAll("[data-password-toggle]").forEach(function (toggle) {
      var password = document.getElementById(toggle.getAttribute("aria-controls"));
      if (!password) return;
      var eyeOpen = toggle.querySelector("[data-eye-open]");
      var eyeClosed = toggle.querySelector("[data-eye-closed]");
      var fieldLabel = toggle.getAttribute("aria-label").replace(/^Show /, "");

      toggle.addEventListener("click", function () {
        var showing = password.type === "text";
        password.type = showing ? "password" : "text";
        toggle.setAttribute("aria-pressed", String(!showing));
        toggle.setAttribute(
          "aria-label",
          (showing ? "Show " : "Hide ") + fieldLabel
        );
        var textLabel = toggle.querySelector("[data-password-label]");
        if (textLabel) textLabel.textContent = showing ? "Show" : "Hide";
        if (eyeOpen && eyeClosed) {
          eyeOpen.classList.toggle("password-toggle__hidden", !showing);
          eyeClosed.classList.toggle("password-toggle__hidden", showing);
        }
      });
    });
  }

  function initLogin() {
    var form = document.querySelector("[data-login-form]");
    if (!form) return;

    var password = form.querySelector("#current-password");
    var status = form.querySelector("[data-form-status]");
    var statusMessage = status ? status.querySelector("[data-form-status-message]") : null;
    var email = form.querySelector("#email");
    var forgot = form.querySelector("[data-forgot-password]");
    var submit = form.querySelector("[data-login-submit]");

    function showStatus(message, kind) {
      if (!status || !statusMessage) return;
      statusMessage.textContent = message;
      status.classList.remove("is-hidden", "login-alert--success", "login-alert--info");
      if (kind === "success") status.classList.add("login-alert--success");
      if (kind === "info") status.classList.add("login-alert--info");
    }

    function clearStatus() {
      if (!status) return;
      status.classList.add("is-hidden");
      status.classList.remove("login-alert--success", "login-alert--info");
      if (email) email.removeAttribute("aria-invalid");
      if (password) password.removeAttribute("aria-invalid");
    }

    [email, password].forEach(function (input) {
      if (input) input.addEventListener("input", clearStatus);
    });

    if (forgot && email) {
      forgot.addEventListener("click", function () {
        if (!email.checkValidity()) {
          email.focus();
          email.reportValidity();
          return;
        }

        forgot.disabled = true;
        showStatus("Sending a secure reset link…", "info");

        fetch("/api/auth/forgot-password", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]').value
          },
          body: JSON.stringify({ email: email.value.trim() })
        })
          .then(function (response) {
            if (!response.ok) throw new Error("reset-request-failed");
            showStatus("If that account exists, a password reset link has been sent.", "success");
          })
          .catch(function () {
            showStatus("We couldn’t send a reset link right now. Please try again shortly.", "error");
          })
          .finally(function () {
            forgot.disabled = false;
          });
      });
    }

    form.addEventListener("submit", function () {
      if (!form.checkValidity() || !submit) return;
      submit.disabled = true;
      submit.classList.add("is-submitting");
      submit.setAttribute("aria-busy", "true");
    });
  }

  // A password form shows it is saving and cannot be sent twice: the reset
  // link's page, and the change asked for at first sign-in (owner,
  // 2026-11-06: a partner's new password looked as if it had not saved).
  // pageshow gives the button back when the browser returns to the page.
  function initBusySubmit(formSelector, submitSelector) {
    var form = document.querySelector(formSelector);
    var submit = form ? form.querySelector(submitSelector) : null;
    if (!form || !submit) return;
    form.addEventListener("submit", function () {
      if (!form.checkValidity()) return;
      submit.disabled = true;
      submit.classList.add("is-submitting");
      submit.setAttribute("aria-busy", "true");
    });
    window.addEventListener("pageshow", function () {
      submit.disabled = false;
      submit.classList.remove("is-submitting");
      submit.removeAttribute("aria-busy");
    });
  }

  function initResetPassword() {
    initBusySubmit("[data-reset-password-form]", "[data-reset-password-submit]");
    initBusySubmit("[data-change-password-form]", "[data-change-password-submit]");
  }

  // "That was not sent" (pages/auth/request_not_sent.html). Going back through
  // history returns to the form with what was typed still in it, and
  // csrf-sync.js gives it the current token as the page is shown again. The
  // link's own address is the fallback when there is no page to go back to.
  function initGoBack() {
    var back = document.querySelector("[data-go-back]");
    if (!back) return;
    back.addEventListener("click", function (event) {
      if (window.history.length < 2) return;
      event.preventDefault();
      window.history.back();
    });
  }

  function init() {
    initPasswordToggles();
    initLogin();
    initResetPassword();
    initGoBack();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
