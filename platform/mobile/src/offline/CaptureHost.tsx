/**
 * Draws the capture sheet the context asks for, at the app's root: a
 * profile reloading or switching to its offline view beneath it never
 * closes a capture half way, or before its "Saved" word is read.
 */
import { CaptureFlow } from './CaptureFlow';
import { useOffline } from './OfflineContext';

export function CaptureHost() {
  const { captureRequest, closeCapture } = useOffline();
  if (!captureRequest) return null;
  return <CaptureFlow key={`${captureRequest.school.schoolId}:${captureRequest.target}`} school={captureRequest.school} target={captureRequest.target} onClose={closeCapture} />;
}
