import { spawnSync } from 'node:child_process';

const action = process.argv[2];
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const uv = process.env.UV_BIN ?? (process.platform === 'win32' ? 'uv.exe' : 'uv');

function run(command, args) {
  const result = spawnSync(command, args, { stdio: 'inherit' });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const api = ['run', '--directory', 'apps/api'];
const cli = ['run', '--directory', 'apps/cli'];

switch (action) {
  case 'generate-api':
    run(uv, [...api, 'python', 'scripts/export_openapi.py']);
    run(npm, ['--workspace', '@review-agent/web', 'run', 'generate:api']);
    break;
  case 'format':
    run(npm, ['exec', 'prettier', '--', '--write', '.']);
    run(uv, [...api, 'ruff', 'format', '.']);
    run(uv, [...cli, 'ruff', 'format', '.']);
    break;
  case 'format-check':
    run(npm, ['exec', 'prettier', '--', '--check', '.']);
    run(uv, [...api, 'ruff', 'format', '--check', '.']);
    run(uv, [...cli, 'ruff', 'format', '--check', '.']);
    break;
  case 'typecheck':
    run(npm, ['--workspace', '@review-agent/web', 'run', 'typecheck']);
    run(uv, [...api, 'mypy', 'src']);
    run(uv, [...cli, 'mypy', 'src']);
    break;
  case 'test':
    run(npm, ['--workspace', '@review-agent/web', 'run', 'test']);
    run(uv, [...api, 'pytest']);
    run(uv, [...cli, 'pytest']);
    break;
  case 'build':
    run(npm, ['--workspace', '@review-agent/web', 'run', 'build']);
    run(uv, ['build', '--directory', 'apps/api']);
    run(uv, ['build', '--directory', 'apps/cli']);
    break;
  default:
    console.error(`未知质量命令：${action ?? ''}`);
    process.exit(1);
}
