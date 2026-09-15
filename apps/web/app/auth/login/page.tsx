import { Suspense } from 'react';
import LoginForm from './login-form';

export default function LoginPage() {
  return (
    <main>
      <p className="eyebrow">Review Agent · 登录</p>
      <Suspense fallback={<p>正在准备登录表单…</p>}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
