import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('首页明确限制上传范围', async () => {
  const page = await readFile(new URL('../app/page.tsx', import.meta.url), 'utf8');

  assert.match(page, /完整仓库/);
  assert.match(page, /Git diff/);
  assert.match(page, /auth\/login/);
});

test('邮箱链接验证页只在用户确认后换取会话', async () => {
  const verify = await readFile(
    new URL('../app/auth/verify/verify-form.tsx', import.meta.url),
    'utf8',
  );

  assert.match(verify, /完成登录/);
  assert.match(verify, /credentials: 'include'/);
  assert.match(verify, /history\.replaceState/);
  assert.match(verify, /auth\/email-login\/verify/);
});

test('组织创建页使用生成的组织契约', async () => {
  const onboarding = await readFile(
    new URL('../app/onboarding/onboarding-form.tsx', import.meta.url),
    'utf8',
  );

  assert.match(onboarding, /OrganizationCreate/);
  assert.match(onboarding, /v1\/organizations/);
});
