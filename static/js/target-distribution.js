/* The distribution picker: one holder at a time, and a balance that moves.
 *
 * Both distribution drawers (IA → Program Leads, PL → CCEOs) share this
 * behaviour. The old drawers rendered every eligible holder pre-filled with a
 * recommendation and treated the balance as server-rendered only — editing a
 * number greyed the panel out until a draft round-trip. That inverted the
 * mental model of the person distributing, which is an envelope: pick someone,
 * give them a number, watch what is left fall until it reaches zero.
 *
 * So the drawer now starts with only the holders who already have an
 * allocation; everyone else waits in a dropdown. Every keystroke recomputes
 * the remaining figure client-side, and Approve only arms at exactly zero.
 * The arithmetic here is a PREVIEW for the hand doing the work — the engine
 * re-reconciles server-side on save and approve, and refuses anything that
 * does not balance, so a doctored DOM changes nothing.
 *
 * Markup contract (per form):
 *   form[data-alloc-picker]            data-expected, data-summable,
 *                                      data-core-expected, data-client-expected
 *   select[data-alloc-select]          one option per hidden holder
 *   [data-alloc-rows] > [data-alloc-row][data-holder=ID]  (hidden until added)
 *   input[data-alloc-target]           the holder's target (empty ⇒ removed)
 *   input[data-alloc-core] / [data-alloc-client]           optional splits
 *   [data-alloc-remove]                returns the row to the dropdown
 *   [data-live-remaining] / [data-live-core] / [data-live-client]
 *   [data-alloc-approve]               armed only at zero balance
 */
(() => {
  const parse = (value) => {
    const n = parseFloat(String(value ?? '').replace(/,/g, ''));
    return Number.isFinite(n) ? n : 0;
  };
  const fmt = (n) =>
    n.toLocaleString('en-US', { maximumFractionDigits: 2 });

  const visibleRows = (form) =>
    [...form.querySelectorAll('[data-alloc-row]:not([hidden])')];

  // Every write below is guarded by an equality check. The observer that
  // re-boots freshly inserted drawer fragments listens for childList
  // mutations, and setting textContent IS one — an unconditional write here
  // therefore feeds the observer that schedules it, which pegged a renderer
  // solid the first time this shipped. Writing only on change breaks the
  // cycle at its source rather than debouncing around it.
  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };

  const recount = (form) => {
    const select = form.querySelector('[data-alloc-select]');
    if (select) {
      for (const option of select.options) {
        if (!option.value) continue;
        const row = form.querySelector(
          `[data-alloc-row][data-holder="${CSS.escape(option.value)}"]`
        );
        const taken = !!row && !row.hidden;
        if (option.disabled !== taken) option.disabled = taken;
        if (option.hidden !== taken) option.hidden = taken;
      }
      if (select.selectedOptions[0]?.disabled) select.value = '';
    }

    if (form.dataset.summable !== 'true') return; // rates never sum

    const expected = parse(form.dataset.expected);
    const sums = { t: 0, core: 0, client: 0 };
    for (const row of visibleRows(form)) {
      sums.t += parse(row.querySelector('[data-alloc-target]')?.value);
      sums.core += parse(row.querySelector('[data-alloc-core]')?.value);
      sums.client += parse(row.querySelector('[data-alloc-client]')?.value);
    }
    const remaining = Math.round((expected - sums.t) * 100) / 100;

    const panel = form.querySelector('[data-live-panel]');
    setText(form.querySelector('[data-live-remaining]'), fmt(remaining));
    panel?.classList.toggle('is-zero', remaining === 0);
    panel?.classList.toggle('is-over', remaining < 0);
    setText(
      form.querySelector('[data-live-hint]'),
      remaining === 0
        ? 'Fully distributed — ready to approve'
        : remaining < 0
          ? `Over-allocated by ${fmt(-remaining)} — reduce a target`
          : 'Left to distribute'
    );

    for (const [key, attr] of [
      ['coreExpected', 'data-live-core'],
      ['clientExpected', 'data-live-client'],
    ]) {
      const el = form.querySelector(`[${attr}]`);
      if (!el || form.dataset[key] === '') continue;
      const rest =
        Math.round(
          (parse(form.dataset[key]) -
            (attr === 'data-live-core' ? sums.core : sums.client)) * 100
        ) / 100;
      setText(el, fmt(rest));
      el.classList.toggle('is-off', rest !== 0);
    }

    const approve = form.querySelector('[data-alloc-approve]');
    if (approve) {
      const ready = remaining === 0 && visibleRows(form).length > 0;
      if (approve.disabled !== !ready) approve.disabled = !ready;
      approve.classList.toggle('is-ready', ready);
    }
  };

  const addHolder = (form) => {
    const select = form.querySelector('[data-alloc-select]');
    const id = select?.value;
    if (!id) return;
    const row = form.querySelector(
      `[data-alloc-row][data-holder="${CSS.escape(id)}"]`
    );
    if (!row) return;
    row.hidden = false;
    select.value = '';
    recount(form);
    row.querySelector('[data-alloc-target]')?.focus();
  };

  document.addEventListener('click', (event) => {
    const add = event.target.closest('[data-alloc-add]');
    if (add) {
      event.preventDefault();
      addHolder(add.closest('[data-alloc-picker]'));
      return;
    }
    const remove = event.target.closest('[data-alloc-remove]');
    if (remove) {
      event.preventDefault();
      const row = remove.closest('[data-alloc-row]');
      const form = remove.closest('[data-alloc-picker]');
      if (!row || !form) return;
      // Hidden inputs still submit: an emptied target posts "" and the server
      // deletes the draft. That is the removal contract, not a DOM detail.
      row.hidden = true;
      for (const input of row.querySelectorAll('input')) input.value = '';
      recount(form);
    }
  });

  document.addEventListener('input', (event) => {
    const form = event.target.closest('[data-alloc-picker]');
    if (form) recount(form);
  });

  // Adding via Enter in the select, and first paint after a drawer fragment
  // lands (both drawers fetch their form lazily).
  document.addEventListener('change', (event) => {
    if (event.target.matches('[data-alloc-select]')) {
      addHolder(event.target.closest('[data-alloc-picker]'));
    }
  });

  // Boot newly inserted drawer fragments only: the observer reacts to forms
  // it has not seen, never to recount's own writes.
  const seen = new WeakSet();
  const boot = () => {
    for (const form of document.querySelectorAll('[data-alloc-picker]')) {
      if (seen.has(form)) continue;
      seen.add(form);
      recount(form);
    }
  };
  new MutationObserver(boot).observe(document.body, {
    childList: true,
    subtree: true,
  });
  boot();
})();
