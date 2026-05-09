/**
 * Render script llamado desde Python como subproceso.
 * Argumentos: <props.json> <output.mp4>
 * Emite líneas JSON a stdout: { progress: 0-100, status: string }
 */
import path from 'path';
import { fileURLToPath } from 'url';
import { readFileSync, existsSync, readdirSync } from 'fs';
import os from 'os';
import { bundle } from '@remotion/bundler';
import { renderMedia, selectComposition } from '@remotion/renderer';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function emit(progress, status) {
  process.stdout.write(JSON.stringify({ progress, status }) + '\n');
}

function findChromium() {
  // 1. Variable de entorno (Dockerfile / Railway)
  if (process.env.CHROME_EXECUTABLE && existsSync(process.env.CHROME_EXECUTABLE)) {
    return process.env.CHROME_EXECUTABLE;
  }

  // 2. Rutas comunes en Linux (Dockerfile instala chromium)
  const linuxPaths = [
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
  ];
  for (const p of linuxPaths) {
    if (existsSync(p)) return p;
  }

  // 3. Playwright en Linux (~/.cache/ms-playwright)
  const linuxBase = path.join(os.homedir(), '.cache', 'ms-playwright');
  if (existsSync(linuxBase)) {
    for (const dir of readdirSync(linuxBase).filter(d => d.startsWith('chromium-'))) {
      const exe = path.join(linuxBase, dir, 'chrome-linux', 'chrome');
      if (existsSync(exe)) return exe;
    }
  }

  // 4. Playwright en Windows (desarrollo local)
  const winBase = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
  if (existsSync(winBase)) {
    for (const dir of readdirSync(winBase).filter(d => d.startsWith('chromium-'))) {
      const exe = path.join(winBase, dir, 'chrome-win', 'chrome.exe');
      if (existsSync(exe)) return exe;
    }
  }

  return undefined;
}

async function main() {
  const propsFile  = process.argv[2];
  const outputFile = process.argv[3];

  if (!propsFile || !outputFile) {
    process.stderr.write('Uso: node render.js <props.json> <output.mp4>\n');
    process.exit(1);
  }

  const inputProps = JSON.parse(readFileSync(propsFile, 'utf8'));

  emit(2, 'bundling');

  const serveUrl = await bundle({
    entryPoint: path.resolve(__dirname, 'src', 'index.ts'),
    onProgress: (p) => emit(2 + Math.round(p * 0.13), 'bundling'),
  });

  emit(15, 'selecting');

  const composition = await selectComposition({
    serveUrl,
    id: 'PropertyReel',
    inputProps,
  });

  emit(18, 'rendering');

  const browserExecutable = findChromium();

  await renderMedia({
    composition,
    serveUrl,
    codec: 'h264',
    outputLocation: outputFile,
    inputProps,
    ...(browserExecutable ? { browserExecutable } : {}),
    onProgress: ({ progress }) => {
      emit(18 + Math.round(progress * 79), 'rendering');
    },
  });

  emit(100, 'done');
}

main().catch(err => {
  process.stderr.write('ERROR: ' + err.message + '\n' + (err.stack || '') + '\n');
  process.exit(1);
});
