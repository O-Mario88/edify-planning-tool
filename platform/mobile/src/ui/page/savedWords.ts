/**
 * What the app says when a save lands. The existing web's words, "Saved.
 * Press Refresh to see it on the page. ×", are true on its pages, which do
 * not redraw after a save (owner, 2026-10-12); the app reads the page again
 * after every save, so it says "Saved." and keeps any other sentence the save
 * gave (a notice, a warning). Owner, 2026-11-21 ("please proceed", doc 184
 * §4). Pure, so it is tested apart from the screens.
 */
const REFRESH = /\s*Press Refresh to see it on the page\.?/i;
const CLOSE = /\s*×\s*$/;

export function savedWords(message: string): string {
  const words = message.replace(REFRESH, '').replace(CLOSE, '').trim();
  return words || 'Saved.';
}
