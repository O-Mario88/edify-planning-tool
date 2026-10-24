// Writes the server the app opens (capacitor.config.js) into the offline
// page, so its "Try again" goes back to that server. Runs before every sync.
// The URL becomes a JSON string constant in the page's script: the page never
// reads it back out of its own markup.
const fs = require("node:fs");
const path = require("node:path");
const config = require("../capacitor.config.js");

const page = path.join(__dirname, "..", "www", "offline.html");
const html = fs.readFileSync(page, "utf8");
const constant = /var EDIFY_SERVER = "(?:[^"\\]|\\.)*";/;
if (!constant.test(html)) {
  throw new Error("offline.html has no EDIFY_SERVER constant to stamp");
}
const literal = JSON.stringify(config.server.url).replace(/</g, "\\u003c");
fs.writeFileSync(page, html.replace(constant, `var EDIFY_SERVER = ${literal};`));
console.log(`offline page retries ${config.server.url}`);
