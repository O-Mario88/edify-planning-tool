// Writes the server the app opens (capacitor.config.js) into the offline
// page, so its "Try again" goes back to that server. Runs before every sync.
const fs = require("node:fs");
const path = require("node:path");
const config = require("../capacitor.config.js");

const page = path.join(__dirname, "..", "www", "offline.html");
const html = fs.readFileSync(page, "utf8");
const stamped = html.replace(/data-server="[^"]*"/, `data-server="${config.server.url}"`);
if (stamped === html && !html.includes(`data-server="${config.server.url}"`)) {
  throw new Error("offline.html has no data-server attribute to stamp");
}
fs.writeFileSync(page, stamped);
console.log(`offline page retries ${config.server.url}`);
