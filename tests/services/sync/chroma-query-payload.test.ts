import { describe, expect, it } from 'bun:test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const fixture = String.raw`
  import { ChromaSync } from './src/services/sync/ChromaSync.ts';
  import { ChromaMcpManager } from './src/services/sync/ChromaMcpManager.ts';
  const docs = Array.from({ length: 10000 }, (_, n) => ({
    id: 'obs_' + (n + 1) + '_narrative', document: 'x'.repeat(2048),
    metadata: { project: 'budget-project', doc_type: 'observation', sqlite_id: n + 1 },
    distance: n / 10000,
  }));
  const calls = [];
  // Only vector transport is controlled: the actual ChromaSync chooses the
  // request fields, falls back after its capped probe, and deduplicates rows.
  ChromaMcpManager.getInstance().callTool = async (tool, args) => {
    if (tool === 'chroma_create_collection') return {};
    if (tool !== 'chroma_query_documents') throw new Error('Unexpected tool: ' + tool);
    const hits = docs.slice(0, args.n_results);
    const response = {
      ids: [hits.map(d => d.id)],
      metadatas: [hits.map(d => d.metadata)], distances: [hits.map(d => d.distance)],
      documents: args.include.includes('documents') ? [hits.map(d => d.document)] : null,
    };
    calls.push({ count: args.n_results, include: args.include,
      responseBytes: Buffer.byteLength(JSON.stringify(response)),
      documentBytes: response.documents?.[0].reduce((n, text) => n + Buffer.byteLength(text), 0) ?? 0 });
    return response;
  };
  const sync = new ChromaSync('budget-project');
  const results = [];
  for (const where of [undefined, { project: 'budget-project' }]) {
    const progress = { exhausted: false };
    const out = await sync.queryChroma('large corpus', 10000, where, progress);
    results.push({ count: out.ids.length, first: out.ids[0], last: out.ids.at(-1),
      firstMetadata: out.metadatas[0], lastDistance: out.distances.at(-1), exhausted: progress.exhausted });
  }
  console.log(JSON.stringify({ results, calls }));
`;

describe('large Chroma query payload consumed by semantic hydration', () => {
  it('keeps the requested candidates and metadata without transporting unused document text', () => {
    const dir = mkdtempSync(join(tmpdir(), 'chroma-query-payload-'));
    try {
      const child = Bun.spawnSync([process.execPath, '--preload', './tests/preload.ts', '-e', fixture], {
        cwd: join(import.meta.dir, '../../..'), stdout: 'pipe', stderr: 'pipe',
        env: { ...process.env, DO_NOT_TRACK: '1', CLAUDE_MEM_DATA_DIR: join(dir, 'data'), CLAUDE_CONFIG_DIR: join(dir, 'config') },
      });
      expect(child.exitCode).toBe(0);
      if (child.exitCode !== 0) throw new Error(new TextDecoder().decode(child.stderr));
      const result = JSON.parse(new TextDecoder().decode(child.stdout).trim().split('\n').at(-1)!);
      console.log('Synthetic MCP payload receipt:', JSON.stringify(result.calls));
      expect(result.results).toEqual(Array.from({ length: 2 }, () => ({ count: 10000, first: 1, last: 10000,
        firstMetadata: { project: 'budget-project', doc_type: 'observation', sqlite_id: 1 }, lastDistance: 0.9999, exhausted: false })));
      expect(result.calls.map((c: { count: number }) => c.count)).toEqual([10000, 2000, 10000]);
      expect(result.calls.every((c: { include: string[] }) => !c.include.includes('documents'))).toBe(true);
      expect(result.calls.every((c: { documentBytes: number }) => c.documentBytes === 0)).toBe(true);
      expect(result.calls.every((c: { responseBytes: number }) => c.responseBytes < 2000000)).toBe(true);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
});
