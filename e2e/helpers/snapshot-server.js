const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

// Serve real rendered snapshots with normal browser asset caching. Intercepting
// every request disables that cache and reparses the whole CSS bundle per page.
// This server is loopback-only, never writes data, and blocks external resources.
async function snapshotServer(root) {
  let html = '';
  const assets = new Map();
  const types = {'.css':'text/css','.js':'text/javascript','.svg':'image/svg+xml',
    '.woff2':'font/woff2','.woff':'font/woff','.png':'image/png','.jpg':'image/jpeg',
    '.webp':'image/webp','.ico':'image/x-icon'};
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method !== 'GET') { response.writeHead(204); response.end(); return; }
    if (pathname === '/page') {
      response.writeHead(200, {
        'Content-Type':'text/html; charset=utf-8', 'Cache-Control':'no-store',
        'Content-Security-Policy':"default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; font-src 'self' data:"
      });
      response.end(html); return;
    }
    const file = path.resolve(root, '.' + decodeURIComponent(pathname));
    if (file.startsWith(path.join(root, 'static') + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) {
      if (!assets.has(file)) assets.set(file, fs.readFileSync(file));
      response.writeHead(200, {'Content-Type':types[path.extname(file)] || 'application/octet-stream',
        'Cache-Control':'public, max-age=86400'});
      response.end(assets.get(file)); return;
    }
    response.writeHead(204); response.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {origin:`http://127.0.0.1:${server.address().port}`,
    setHtml(value) { html = value; },
    async close() { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }};
}
module.exports = {snapshotServer};
