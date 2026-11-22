import type { Metadata } from 'next';

import { SsaUploadCenterView } from '@/components/pages/SsaUploadCenterView';

export const metadata: Metadata = {
  title: 'Bulk Upload Center — Edify',
};

export default function SsaUploadPage() {
  return <SsaUploadCenterView />;
}
