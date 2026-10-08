// What a page says went wrong, for the specs that end on "and nothing did".
//
// Not counted: what a page reports while it is being left. Safari stops a
// page's requests the moment the reader follows a link, and tells the page,
// which is still running until the next one arrives: htmx logs the request it
// lost ("htmx:sendError"), and a live stream opened in that moment is refused
// ("... /api/realtime/stream due to access control checks"). Neither can
// happen on a page that is being read, and Chromium says nothing in either
// case, so a spec that counted them failed in WebKit alone (Browser Matrix,
// to 2026-10-08). Everything a page reports while it is open still counts.

/**
 * Collects the page's errors into the array it returns.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{ console?: boolean, ignore?: RegExp }} [options] `console` also
 *   collects console errors; `ignore` leaves out messages the spec expects.
 */
function watchPageErrors(page, options = {}) {
  const errors = [];
  let leaving = false;
  const main = request => request.isNavigationRequest() && request.frame() === page.mainFrame();
  page.on('request', request => { if (main(request)) leaving = true; });
  // A page the spec itself sends elsewhere has begun to leave before the
  // browser reports the new page's request: Safari has stopped the old page's
  // requests by then, and htmx has already logged the one it lost.
  for (const method of ['goto', 'reload', 'goBack', 'goForward']) {
    const navigate = page[method].bind(page);
    page[method] = (...args) => { leaving = true; return navigate(...args); };
  }
  // The next page has arrived, or the navigation was called off.
  page.on('framenavigated', frame => { if (frame === page.mainFrame()) leaving = false; });
  page.on('requestfailed', request => { if (main(request)) leaving = false; });
  const keep = text => !leaving && !(options.ignore && options.ignore.test(text));
  page.on('pageerror', error => { if (keep(error.message)) errors.push(error.message); });
  if (options.console) {
    page.on('console', message => {
      if (message.type() === 'error' && keep(message.text())) errors.push(message.text());
    });
  }
  return errors;
}

module.exports = { watchPageErrors };
