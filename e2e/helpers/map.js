// The dashboard map is a portrait sheet bounded by the window (owner,
// 2026-09-16), so it should be readable without scrolling once its card is in
// view. Measure the drawing with its card flush under the top bar.
// scrollIntoView would leave the workspace's scroll margin above the card, so
// scroll by the exact distance.
async function mapInView(page) {
  return page.evaluate(() => {
    const card = document.querySelector('.analytics-geo-card');
    const topbar = document.querySelector('.edify-topbar');
    document.querySelector('main').scrollBy({
      top: card.getBoundingClientRect().top - topbar.getBoundingClientRect().bottom,
      behavior: 'instant',
    });
    const drawing = card.querySelector('.sr-map-viewport > svg').getBoundingClientRect();
    return {
      top: Math.round(drawing.top),
      bottom: Math.round(drawing.bottom),
      height: Math.round(drawing.height),
      topbarBottom: Math.round(topbar.getBoundingClientRect().bottom),
      windowHeight: innerHeight,
    };
  });
}

module.exports = { mapInView };
