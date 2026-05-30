// Deprecated: canonical URL is /data-intake/upload (the Upload Center —
// templates → populate → validate → submit). The earlier /data-upload
// was a thin one-card stub; users should always land in the full hub.

import { permanentRedirect } from "next/navigation";

export default function DeprecatedDataUpload() {
  permanentRedirect("/data-intake/upload");
}
