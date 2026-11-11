// The public loan form, made easier where JavaScript runs. Without it the
// form still works: the server validates everything, computes the total and
// accepts typed places.
(function () {
  'use strict';
  var form = document.getElementById('loan-form');
  if (!form) {
    return;
  }

  function field(name) {
    return form.elements.namedItem(name);
  }

  // Total enrollment = boys + girls, never typed in.
  var total = document.getElementById('total-enrollment');
  function wholeNumber(value) {
    var cleaned = String(value || '').replace(/,/g, '').trim();
    return /^\d+$/.test(cleaned) ? parseInt(cleaned, 10) : null;
  }
  function updateTotal() {
    var boys = wholeNumber(field('boys').value);
    var girls = wholeNumber(field('girls').value);
    total.textContent = boys === null || girls === null ? '—' : (boys + girls).toLocaleString('en-US');
  }
  ['boys', 'girls'].forEach(function (name) {
    field(name).addEventListener('input', updateTotal);
  });
  updateTotal();

  // UGX amounts are shown grouped (1,500,000) as they are typed.
  function grouped(value) {
    var digits = String(value || '').replace(/[^\d]/g, '');
    return digits ? Number(digits).toLocaleString('en-US') : '';
  }
  Array.prototype.forEach.call(form.querySelectorAll('[data-money]'), function (input) {
    input.addEventListener('blur', function () {
      if (/^[\d,\s]+$/.test(input.value)) {
        input.value = grouped(input.value);
      }
    });
  });

  // Sub-counties and parishes follow the chosen district, where Edify has
  // them; any name may still be typed.
  var timers = {};
  function loadPlaces(list, query) {
    clearTimeout(timers[list.id]);
    timers[list.id] = setTimeout(function () {
      var request = new XMLHttpRequest();
      request.open('GET', form.getAttribute('data-places') + '?' + query);
      request.onload = function () {
        if (request.status !== 200) {
          return;
        }
        var names = JSON.parse(request.responseText).places || [];
        list.textContent = '';
        names.forEach(function (name) {
          var option = document.createElement('option');
          option.value = name;
          list.appendChild(option);
        });
      };
      request.send();
    }, 250);
  }
  var subCounties = document.getElementById('sub-counties');
  var parishes = document.getElementById('parishes');
  field('district').addEventListener('change', function () {
    loadPlaces(subCounties, 'district=' + encodeURIComponent(field('district').value));
  });
  field('sub_county').addEventListener('change', function () {
    loadPlaces(parishes, 'district=' + encodeURIComponent(field('district').value) +
      '&sub_county=' + encodeURIComponent(field('sub_county').value));
  });

  // "Other" asks for a short description.
  var other = document.getElementById('purpose-other');
  function updatePurpose() {
    var isOther = field('purpose').value === 'other';
    other.hidden = !isOther;
    field('purpose_other').required = isOther;
  }
  field('purpose').addEventListener('change', updatePurpose);
  updatePurpose();

  // The chosen lender's approved description.
  var note = document.getElementById('lender-note');
  function updateLender() {
    var select = field('partner');
    var chosen = select.options[select.selectedIndex];
    note.textContent = chosen ? chosen.getAttribute('data-description') || '' : '';
  }
  field('partner').addEventListener('change', updateLender);
  updateLender();

  // One tap sends once. (The server also refuses a second copy.)
  var button = document.getElementById('submit-button');
  form.addEventListener('submit', function () {
    if (form.getAttribute('data-sending') === 'yes') {
      return;
    }
    form.setAttribute('data-sending', 'yes');
    setTimeout(function () {
      button.disabled = true;
      button.textContent = 'Sending your application…';
    }, 0);
  });

})();

(function () {
  'use strict';
  var copy = document.getElementById('copy-reference');
  if (!copy || !navigator.clipboard) {
    return;
  }
  copy.hidden = false;
  copy.addEventListener('click', function () {
    navigator.clipboard.writeText(copy.getAttribute('data-reference')).then(function () {
      copy.textContent = 'Copied';
    });
  });
})();
