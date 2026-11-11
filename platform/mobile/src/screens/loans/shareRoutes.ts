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

const EMAIL = /^[^\s@?&#/:]+@[^\s@?&#/:]+\.[^\s@?&#/:]+$/;

/** A phone number as dialled ("+256772000111"), or "" when it is not one. */
function dialled(phone: string): string {
  const digits = phone.replace(/[\s().-]/g, '');
  return /^\+?\d{6,15}$/.test(digits) ? digits : '';
}

/**
 * The link that opens WhatsApp, the SMS app or the mail app with the text.
 * `to` addresses it (a phone number, or an email address) when it is known;
 * otherwise the person chooses the contact in their own app.
 */
export function shareHref(channel: 'whatsapp' | 'sms' | 'email', text: ShareText, os: string, to = ''): string {
  const body = encodeURIComponent(text.body);
  switch (channel) {
    case 'whatsapp': {
      // wa.me opens the app on a phone and WhatsApp Web in a browser. It
      // needs the country code, so a local number leaves the choice open.
      const phone = dialled(to);
      return `https://wa.me/${phone.startsWith('+') ? phone.slice(1) : ''}?text=${body}`;
    }
    case 'sms':
      // iOS reads the body after "&", Android after "?".
      return `sms:${dialled(to)}${os === 'ios' ? '&' : '?'}body=${body}`;
    case 'email':
      return `mailto:${EMAIL.test(to.trim()) ? to.trim() : ''}?subject=${encodeURIComponent(text.subject ?? '')}&body=${body}`;
  }
}

/** The message that hands a new Cluster Leader their set-password link. */
export function inviteText(name: string, clusterName: string, link: string): ShareText {
  const first = name.trim().split(/\s+/)[0] || 'there';
  return {
    subject: 'Your Edify Cluster Leader account',
    body:
      `Hello ${first}, you are now the Cluster Leader for ${clusterName} on Edify. ` +
      `Open this link to set your password and sign in: ${link}`,
  };
}

/** Only an HTTPS link (or a developer's own machine) is ever shared. */
export function isShareableUrl(url: string): boolean {
  return /^https:\/\/[^\s/]+\//.test(url + '/') || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(url + '/');
}

/** "Sent as 2 text messages" for a long SMS; nothing for one. */
export function smsNote(parts: number): string {
  return parts > 1 ? `Sent as ${parts} text messages.` : '';
}
