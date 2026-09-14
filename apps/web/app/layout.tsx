import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import './styles.css';

export const metadata: Metadata = {
  title: 'Review Agent',
  description: '只上传 diff 的代码审阅助手',
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
