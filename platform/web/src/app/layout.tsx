import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

export const metadata: Metadata = {
  title: 'Edify Command Center',
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#dbe4eb',
};

/*
 * The saved theme is applied before the page paints, as the existing web's
 * base.html does, from the same per-browser key ("edify_theme": light, dark
 * or system). It is a viewer's preference, not data.
 */
const THEME_SCRIPT = `(function(){try{var p=localStorage.getItem('edify_theme')||'light';
var d=p==='dark'||(p==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);
var h=document.documentElement;h.classList.remove('light','theme-dark','dark');
h.classList.add(d?'theme-dark':'light');if(d)h.classList.add('dark');h.dataset.theme=d?'dark':'light';}catch(e){}})();`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="light h-full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="h-full">{children}</body>
    </html>
  );
}
