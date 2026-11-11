/**
 * Saves a PDF the gateway produced for the signed-in person and opens the
 * phone's share sheet (Files, print, send); on the web it downloads. The
 * bytes never go through a public link.
 */
import { Platform } from 'react-native';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

/** A file name safe on every platform: no path separators or reserved marks. */
export function safeFileName(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|]+/g, '-').trim();
  return cleaned.toLowerCase().endsWith('.pdf') ? cleaned : `${cleaned || 'report'}.pdf`;
}

export async function savePdf(bytes: Uint8Array, fileName: string): Promise<void> {
  const name = safeFileName(fileName);
  if (Platform.OS === 'web') {
    const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: 'application/pdf' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
    return;
  }
  const file = new File(Paths.cache, name);
  if (file.exists) {
    file.delete();
  }
  file.create();
  await file.write(bytes);
  await Sharing.shareAsync(file.uri, { mimeType: 'application/pdf', UTI: 'com.adobe.pdf', dialogTitle: name });
}
