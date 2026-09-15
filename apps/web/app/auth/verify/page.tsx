import { Suspense } from 'react';
import VerifyForm from './verify-form';

export default function VerifyPage() {
  return (
    <main>
      <p className="eyebrow">Review Agent · 登录验证</p>
      <Suspense fallback={<p>正在准备登录验证…</p>}>
        <VerifyForm />
      </Suspense>
    </main>
  );
}
