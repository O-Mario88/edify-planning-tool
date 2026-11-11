import { isShareableUrl, shareHref, smsNote } from '../screens/loans/shareRoutes';

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
