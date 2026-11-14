import { readFile } from 'node:fs/promises';
import path from 'node:path';

/*
 * MapLibre's web worker (maplibre-gl/dist/maplibre-gl-worker.mjs), served
 * from this app: the bundler cannot hand the library its separate worker
 * file, so RouteMap points the library here (setWorkerUrl). Same origin, no
 * third-party script.
 */
let worker: Promise<Buffer> | null = null;

export async function GET() {
  worker ??= readFile(path.join(process.cwd(), 'node_modules', 'maplibre-gl', 'dist', 'maplibre-gl-worker.mjs'));
  return new Response(new Uint8Array(await worker), {
    headers: { 'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'public, max-age=86400' },
  });
}
