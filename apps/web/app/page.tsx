import type { components } from '../lib/api.generated';

type ReviewRequest = components['schemas']['ReviewRequest'];

const exampleRequest: Pick<ReviewRequest, 'diff'> = {
  diff: 'git diff -- src/service.py',
};

export default function Home() {
  return (
    <main>
      <p className="eyebrow">Review Agent · v1</p>
      <h1>只上传本次变更，按需补充上下文。</h1>
      <p>
        请通过 CLI 提交 Git
        diff。审阅器只在证据不足时请求特定文件的有限内容，且不会上传完整仓库、创建提交或阻断合并。
      </p>
      <section aria-label="提交范围">
        <h2>提交范围</h2>
        <ul>
          <li>必需：Git diff</li>
          <li>可选：明确指定路径的最小上下文</li>
          <li>不会提交：完整仓库、密钥文件或合并控制</li>
        </ul>
        <code>{exampleRequest.diff}</code>
      </section>
    </main>
  );
}
