import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

const config = [
  ...nextVitals,
  ...nextTypescript,
  // public/static holds the existing web's own files, copied verbatim by
  // scripts/sync-tokens.mjs (its stylesheets, chart scripts and the pinned
  // ApexCharts): they are checked where they are written, not here.
  { ignores: ['.next/**', 'next-env.d.ts', 'src/gen/**', 'test-results/**', 'playwright-report/**', 'public/static/**'] },
];

export default config;
