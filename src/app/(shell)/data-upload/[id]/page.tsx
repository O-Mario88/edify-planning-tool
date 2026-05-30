// Deprecated: canonical URL is /data-intake/upload/[id].
// Preserves the upload id so direct links to a specific batch still land.

import { permanentRedirect } from "next/navigation";

export default async function DeprecatedDataUploadDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  permanentRedirect(`/data-intake/upload/${id}`);
}
