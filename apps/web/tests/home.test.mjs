import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('首页明确限制上传范围', async () => {
  const page = await readFile(new URL('../app/page.tsx', import.meta.url), 'utf8');

  assert.match(page, /完整仓库/);
  assert.match(page, /Git diff/);
});
