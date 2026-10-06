/* Long selector lists, one selector per alternative.
 *
 * `[class*="label"]` compiles to `:is(.a, .b, … three hundred names)`. A
 * browser files a rule under the class, id or tag its last part names, and a
 * list that long names none, so the rule was tried against every element on
 * every style pass: consistency.css alone was 71% of a whole-page
 * recalculation, and a page load makes dozens (audit, 2026-10-05).
 *
 * A long list is therefore written out as one selector per alternative, in the
 * same rule. Specificity is kept exactly. `:is()` weighs as its heaviest
 * alternative whichever one matched, so a lighter alternative goes inside
 * `:where()`, which weighs nothing, and gets the list's weight back from
 * `:is(*, x)` — that matches every element and weighs as x, so it can never
 * exclude anything. Same elements, same weight, same order, same declarations.
 *
 * Only lists made of parts every supported browser reads are touched. `:is()`
 * forgives an alternative it cannot parse and then ignores its weight, which
 * differs by browser; such a list is left as it was written.
 */
const SPLIT_FROM = 6;
const WEIGHT = '_';
const PLAIN_STATES = new Set([
  'hover', 'focus', 'active', 'disabled', 'enabled', 'checked', 'link', 'visited',
  'first-child', 'last-child', 'only-child', 'first-of-type', 'last-of-type',
  'empty', 'root', 'required', 'optional', 'read-only', 'target'
]);

const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const heavier = (a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]);

// Selectors Level 4 §17, for the parts `portable` admits. null: not modelled.
function specificity(selector) {
  let total = [0, 0, 0];
  for (const node of selector) {
    let part = null;
    if (node.type === 'combinator' || node.type === 'universal') part = [0, 0, 0];
    else if (node.type === 'id') part = [1, 0, 0];
    else if (node.type === 'class' || node.type === 'attribute') part = [0, 1, 0];
    else if (node.type === 'type') part = [0, 0, 1];
    else if (node.type === 'pseudo-class') {
      if (node.kind === 'where') part = [0, 0, 0];
      else if (node.kind === 'is' || node.kind === 'not') part = heaviest(node.selectors);
      else if (PLAIN_STATES.has(node.kind)) part = [0, 1, 0];
    }
    if (!part) return null;
    total = add(total, part);
  }
  return total;
}

function heaviest(selectors) {
  let most = [0, 0, 0];
  for (const selector of selectors) {
    const weight = specificity(selector);
    if (!weight) return null;
    if (heavier(weight, most) > 0) most = weight;
  }
  return most;
}

const portable = selector => specificity(selector) !== null;
const plain = selector =>
  selector.every(node => node.type === 'class' || node.type === 'id' || node.type === 'attribute');

// `:is(a, :is(b, c))` is `:is(a, b, c)`.
const flatten = selectors => selectors.flatMap(selector =>
  selector.length === 1 && selector[0].type === 'pseudo-class' && selector[0].kind === 'is'
    ? flatten(selector[0].selectors)
    : [selector]);

// A selector that weighs exactly `weight` and is only ever written beside `*`.
function weighing([ids, classes, types]) {
  let selector = types ? [{ type: 'type', name: WEIGHT }] : [];
  for (let i = 0; i < ids; i++) selector.push({ type: 'id', name: WEIGHT });
  for (let i = 0; i < classes; i++) selector.push({ type: 'class', name: WEIGHT });
  for (let i = 1; i < types; i++) {
    selector = [{ type: 'type', name: WEIGHT }, { type: 'combinator', value: 'descendant' }, ...selector];
  }
  return selector;
}

function splitLongList(selector) {
  let at = -1;
  let alternatives = null;
  selector.forEach((node, index) => {
    if (node.type !== 'pseudo-class' || node.kind !== 'is') return;
    const flat = flatten(node.selectors);
    if (flat.length < SPLIT_FROM || (alternatives && flat.length <= alternatives.length)) return;
    if (!flat.every(portable)) return;
    at = index;
    alternatives = flat;
  });
  if (at < 0) return selector;
  const weight = heaviest(alternatives);
  const lift = weight.some(Boolean)
    ? [{ type: 'pseudo-class', kind: 'is', selectors: [[{ type: 'universal' }], weighing(weight)] }]
    : [];
  return alternatives.map(alternative => {
    const exact = plain(alternative) && heavier(specificity(alternative), weight) === 0;
    const piece = exact
      ? alternative
      : [{ type: 'pseudo-class', kind: 'where', selectors: [alternative] }, ...lift];
    return [...selector.slice(0, at), ...piece, ...selector.slice(at + 1)];
  });
}

module.exports = { SPLIT_FROM, specificity, splitLongList };
