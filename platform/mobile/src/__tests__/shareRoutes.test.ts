import { inviteText, isShareableUrl, shareHref, smsNote } from '../screens/loans/shareRoutes';

describe('sharing a school loan link', () => {
  const text = { subject: 'Apply for a school loan', body: 'Apply: https://edify.example/loans/apply & more' };

  test('WhatsApp opens with the whole message, the person choosing the contact', () => {
    expect(shareHref('whatsapp', text, 'android')).toBe(
      'https://wa.me/?text=Apply%3A%20https%3A%2F%2Fedify.example%2Floans%2Fapply%20%26%20more',
    );
  });

  test('SMS uses each platform’s own body separator', () => {
    expect(shareHref('sms', text, 'ios').startsWith('sms:&body=Apply')).toBe(true);
    expect(shareHref('sms', text, 'android').startsWith('sms:?body=Apply')).toBe(true);
  });

  test('email carries the subject and body, escaped', () => {
    expect(shareHref('email', text, 'web')).toBe(
      'mailto:?subject=Apply%20for%20a%20school%20loan&body=Apply%3A%20https%3A%2F%2Fedify.example%2Floans%2Fapply%20%26%20more',
    );
  });

  test('only HTTPS links, or a developer machine, are shared', () => {
    expect(isShareableUrl('https://edify.example/loans/apply')).toBe(true);
    expect(isShareableUrl('http://localhost:8090/loans/apply')).toBe(true);
    expect(isShareableUrl('http://edify.example/loans/apply')).toBe(false);
    expect(isShareableUrl('javascript:alert(1)')).toBe(false);
  });

  test('a long SMS says how many messages it takes', () => {
    expect(smsNote(1)).toBe('');
    expect(smsNote(2)).toBe('Sent as 2 text messages.');
  });
});

describe('sending a new Cluster Leader their set-password link', () => {
  const text = { subject: 'Your Edify account', body: 'Set it here: https://edify.example/set-password?token=abc' };

  test('WhatsApp opens the chat with an international number, or lets the person choose', () => {
    expect(shareHref('whatsapp', text, 'ios', '+256 772 000 111').startsWith('https://wa.me/256772000111?text=Set')).toBe(true);
    // A local number cannot be dialled from WhatsApp without its country code.
    expect(shareHref('whatsapp', text, 'ios', '0772 000 111').startsWith('https://wa.me/?text=Set')).toBe(true);
  });

  test('SMS and email are addressed to the leader', () => {
    expect(shareHref('sms', text, 'ios', '0772 000 111').startsWith('sms:0772000111&body=Set')).toBe(true);
    expect(shareHref('sms', text, 'android', '+256772000111').startsWith('sms:+256772000111?body=Set')).toBe(true);
    expect(shareHref('email', text, 'web', 'grace@school.org').startsWith('mailto:grace@school.org?subject=Your%20Edify%20account&body=Set')).toBe(true);
  });

  test('an address that could break the link is left out', () => {
    expect(shareHref('email', text, 'web', 'grace@school.org?cc=x@y.z').startsWith('mailto:?subject=')).toBe(true);
    expect(shareHref('sms', text, 'android', 'call me').startsWith('sms:?body=')).toBe(true);
  });

  test('the message greets the leader, names the cluster and carries the link', () => {
    const message = inviteText('Grace Nakato', 'Cluster B', 'https://edify.example/set-password?token=abc');
    expect(message.subject).toBe('Your Edify Cluster Leader account');
    expect(message.body).toContain('Hello Grace,');
    expect(message.body).toContain('Cluster Leader for Cluster B');
    expect(message.body).toContain('https://edify.example/set-password?token=abc');
  });
});
