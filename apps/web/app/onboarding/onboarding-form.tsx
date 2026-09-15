'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import type { components } from '../../lib/api.generated';

type OrganizationCreate = components['schemas']['OrganizationCreate'];
type OrganizationResponse = components['schemas']['OrganizationResponse'];

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export default function OnboardingForm() {
  const [organization, setOrganization] = useState<OrganizationResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function createOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload: OrganizationCreate = {
      name: String(form.get('name')),
      owner_email: String(form.get('owner_email')),
    };
    const response = await fetch(`${apiBaseUrl}/v1/organizations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      setMessage('创建组织失败，请更换组织名称后重试。');
      return;
    }
    setOrganization((await response.json()) as OrganizationResponse);
    setMessage('组织已创建。请使用管理员邮箱请求登录链接。');
  }

  if (organization) {
    return (
      <section aria-label="组织创建成功">
        <h1>组织已创建</h1>
        <p>组织 ID：{organization.id}</p>
        <p>请保存该 ID；成员登录和邀请会使用它。</p>
        <Link href={`/auth/login?organization_id=${encodeURIComponent(organization.id)}`}>
          使用管理员邮箱登录
        </Link>
      </section>
    );
  }

  return (
    <section aria-label="创建组织">
      <h1>创建组织</h1>
      <form onSubmit={createOrganization}>
        <label>
          组织名称
          <input name="name" required />
        </label>
        <label>
          管理员邮箱
          <input name="owner_email" type="email" required />
        </label>
        <button type="submit">创建组织</button>
      </form>
      {message ? <p role="status">{message}</p> : null}
    </section>
  );
}
