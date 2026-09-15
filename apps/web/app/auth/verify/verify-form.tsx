'use client';

import { useSearchParams } from 'next/navigation';
import { useState } from 'react';
import type { components } from '../../../lib/api.generated';

type EmailLoginVerify = components['schemas']['EmailLoginVerify'];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export default function VerifyForm() {
  const searchParams = useSearchParams();
  const [message, setMessage] = useState<string | null>(null);
  const email = searchParams.get('email');
  const token = searchParams.get('token');
  const organizationId = searchParams.get('organization_id');

  async function verifyLogin() {
    if (!email || !token || !organizationId) {
      setMessage('登录链接不完整或已损坏，请重新请求登录邮件。');
      return;
    }
    const payload: EmailLoginVerify = {
      email,
      token,
      organization_id: organizationId,
    };
    const response = await fetch(`${apiBaseUrl}/v1/auth/email-login/verify`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setMessage('登录链接无效、已过期，或不属于当前组织。');
      return;
    }
    window.history.replaceState({}, '', '/auth/verify');
    setMessage('登录成功。会话由浏览器安全 Cookie 管理。');
  }

  return (
    <section aria-label="登录验证">
      <h1>确认登录</h1>
      <p>为避免邮件扫描器提前消耗链接，请手动确认后再完成登录。</p>
      <button type="button" onClick={verifyLogin}>
        完成登录
      </button>
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
