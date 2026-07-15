(function () {
  "use strict";

  function getCookie(name) {
    var prefix = name + "=";
    var cookies = document.cookie ? document.cookie.split(";") : [];
    for (var index = 0; index < cookies.length; index += 1) {
      var cookie = cookies[index].trim();
      if (cookie.indexOf(prefix) === 0) {
        return decodeURIComponent(cookie.slice(prefix.length));
      }
    }
    return "";
  }

  function initLogin() {
    var form = document.querySelector("[data-login-form]");
    if (!form) return;

    var password = form.querySelector("#current-password");
    var toggle = form.querySelector("[data-password-toggle]");
    var eyeOpen = toggle ? toggle.querySelector("[data-eye-open]") : null;
    var eyeClosed = toggle ? toggle.querySelector("[data-eye-closed]") : null;
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

    if (toggle && password) {
      toggle.addEventListener("click", function () {
        var showing = password.type === "text";
        password.type = showing ? "password" : "text";
        toggle.setAttribute("aria-pressed", String(!showing));
        toggle.setAttribute("aria-label", showing ? "Show password" : "Hide password");
        if (eyeOpen && eyeClosed) {
          eyeOpen.classList.toggle("password-toggle__hidden", !showing);
          eyeClosed.classList.toggle("password-toggle__hidden", showing);
        }
      });
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
            "X-CSRFToken": getCookie("csrftoken")
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLogin);
  } else {
    initLogin();
  }
})();
