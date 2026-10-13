import { expect, it } from 'bun:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { SummaryCard } from '../../../src/ui/viewer/components/SummaryCard.js';
import type { Summary } from '../../../src/ui/viewer/types.js';

const chrome = Bun.which('google-chrome') ?? Bun.which('chromium')
  ?? (existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : null);
if (process.env.CI && !chrome) throw new Error('CI requires Chrome or Chromium for the viewer browser regression.');

(chrome ? it : it.skip)('sizes the Notes lightbulb like the Learned lightbulb in the real summary card', async () => {
  const root = resolve(import.meta.dir, '../../..');
  const template = readFileSync(join(root, 'src/ui/viewer-template.html'), 'utf8');
  const css = template.match(/<style>([\s\S]*?)<\/style>/)![1];
  const markup = renderToStaticMarkup(React.createElement(SummaryCard, {
    summary: { id: 1, project: 'fixture', learned: 'Learned fact', notes: 'Notes fact', created_at_epoch: 1000 } as Summary,
    onDeleted() {},
  }));
  let report!: (result: unknown) => void;
  const result = new Promise<unknown>(resolve => { report = resolve; });
  const server = Bun.serve({ hostname: '127.0.0.1', port: 0, async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === '/') return new Response(`<style>${css}</style>${markup}<script>
      (async () => {
        try {
          await Promise.all([...document.querySelectorAll('.summary-section-icon')].map(img => img.decode()));
          const height = key => document.querySelector('.summary-section-icon--' + key).getBoundingClientRect().height;
          await fetch('/result', { method: 'POST', body: JSON.stringify({ learned: height('learned'), notes: height('notes') }) });
        } catch(error) { await fetch('/result', { method: 'POST', body: JSON.stringify({ failure: String(error) }) }); }
      })();
    </script>`, { headers: { 'Content-Type': 'text/html' } });
    if (url.pathname === '/icon-thick-learned.svg') return new Response(Bun.file(join(root, 'plugin/ui/icon-thick-learned.svg')), { headers: { 'Content-Type': 'image/svg+xml' } });
    if (url.pathname === '/result') { report(await request.json()); return new Response('received'); }
    return new Response('Not found', { status: 404 });
  } });
  const profile = mkdtempSync(join(tmpdir(), 'cmem-notes-icon-'));
  const child = Bun.spawn([chrome!, '--headless', '--no-sandbox', '--disable-gpu', '--disable-background-networking', '--no-first-run', `--user-data-dir=${profile}`, server.url.href], { stdout: 'ignore', stderr: 'ignore' });
  let timeout: ReturnType<typeof setTimeout>;
  try {
    const reported = await Promise.race([result, new Promise(resolve => {
      timeout = setTimeout(() => resolve({ failure: 'Browser did not report icon dimensions' }), 30000);
    })]);
    expect(reported).toEqual({ learned: 18, notes: 18 });
  } finally {
    clearTimeout(timeout!);
    child.kill(); await child.exited;
    server.stop(true);
    rmSync(profile, { recursive: true, force: true });
  }
}, 40000);
