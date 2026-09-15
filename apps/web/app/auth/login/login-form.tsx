'use client';

import { FormEvent, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import type { components } from '../../../lib/api.generated';

type EmailLoginRequest = components['schemas']['EmailLoginRequest'];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export default function LoginForm() {
  const searchParams = useSearchParams();
  const [message, setMessage] = useState<string | null>(null);

  async function requestLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: EmailLoginRequest = {
      email: String(form.get('email')),
      organization_id: String(form.get('organization_id')),
    };
    const response = await fetch(`${apiBaseUrl}/v1/auth/email-login`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setMessage(
      response.ok ? '如该邮箱可登录，登录链接已发送。' : '请求失败，请检查填写内容后重试。',
    );
  }

  return (
    <section aria-label="请求登录链接">
      <h1>邮箱登录</h1>
      <form onSubmit={requestLogin}>
        <label>
          组织 ID
          <input
            name="organization_id"
            defaultValue={searchParams.get('organization_id') ?? ''}
            required
          />
        </label>
        <label>
          邮箱
          <input name="email" type="email" required />
        </label>
        <button type="submit">发送登录链接</button>
      </form>
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
