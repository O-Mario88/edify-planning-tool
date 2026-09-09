/* Rebuild both Tailwind and indexed styles when source classes/styles change. */
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const root = path.resolve(__dirname, '..');
let running = false;
let pending = false;
let timer;

function build() {
  if (running) {
    pending = true;
    return;
  }
  running = true;
  const child = spawn('npm', ['run', 'build:css'], { cwd: root, stdio: 'inherit' });
  child.on('exit', (code) => {
    running = false;
    if (code) console.error(`CSS build failed (${code}); watching for fixes.`);
    if (pending) {
      pending = false;
      build();
    }
  });
}

for (const directory of ['assets/css', 'static/css', 'static/js', 'templates', 'apps']) {
  fs.watch(path.join(root, directory), { recursive: true }, (_event, filename) => {
    if (!filename || !/\.(css|html|py|js)$/.test(filename)) return;
    // These are outputs of the build, not source changes.
    if (directory === 'static/css' && ['main.css', 'tokens.css'].includes(filename)) return;
    clearTimeout(timer);
    timer = setTimeout(build, 150);
  });
}
build();
