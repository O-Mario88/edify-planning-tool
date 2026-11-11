/**
 * How a school loan link leaves the phone: the WhatsApp, SMS and email links
 * that open the person's own app with the approved message filled in. Nothing
 * is sent from here; the person sends it. The messages and links come from
 * the gateway, which builds them from approved templates.
 */

export type ShareChannel = 'whatsapp' | 'sms' | 'email' | 'copy' | 'native' | 'qr';

export interface ShareText {
  readonly subject?: string;
  readonly body: string;
}

/** The link that opens WhatsApp, the SMS app or the mail app with the text. */
export function shareHref(channel: 'whatsapp' | 'sms' | 'email', text: ShareText, os: string): string {
  const body = encodeURIComponent(text.body);
  switch (channel) {
    case 'whatsapp':
      // wa.me opens the app on a phone and WhatsApp Web in a browser; the
      // person chooses the contact.
      return `https://wa.me/?text=${body}`;
    case 'sms':
      // iOS reads the body after "&", Android after "?".
      return os === 'ios' ? `sms:&body=${body}` : `sms:?body=${body}`;
    case 'email':
      return `mailto:?subject=${encodeURIComponent(text.subject ?? '')}&body=${body}`;
  }
}

/** Only an HTTPS link (or a developer's own machine) is ever shared. */
export function isShareableUrl(url: string): boolean {
  return /^https:\/\/[^\s/]+\//.test(url + '/') || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(url + '/');
}

/** "Sent as 2 text messages" for a long SMS; nothing for one. */
export function smsNote(parts: number): string {
  return parts > 1 ? `Sent as ${parts} text messages.` : '';
}
