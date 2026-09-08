(function () {
  "use strict";

  function copyApplicationLink(button) {
    var input = document.getElementById("public-loan-application-url");
    if (!input || !navigator.clipboard) return;

    navigator.clipboard.writeText(input.value).then(function () {
      button.textContent = "Copied";
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy-loan-application-link]");
    if (button) copyApplicationLink(button);
  });
})();
