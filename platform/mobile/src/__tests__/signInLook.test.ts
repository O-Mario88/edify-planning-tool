import { signInLayout, typeSizes } from '../screens/signin/signInLook';

// Values read from the rendered web sign-in page (templates/layouts/login.html)
// at the three widths the owner's references cover.
describe('the sign-in page is laid out as the web draws it', () => {
  test('desktop 1440 x 900: photo panel 770, form 670, card 464', () => {
    const layout = signInLayout(1440, 900);
    expect(layout.isSplit).toBe(true);
    expect(layout.brandWidth).toBeCloseTo(770.2, 1);
    expect(layout.accessWidth).toBeCloseTo(669.8, 1);
    expect(layout.cardWidth).toBe(464);
    expect(layout.innerSide).toBeCloseTo(43.2, 1);
    expect(layout.innerVertical).toBe(44);
    expect(layout.barHeight).toBe(0);
  });

  test('tablet 768: one column, card 464 with a 4 px top line', () => {
    const layout = signInLayout(768, 1024);
    expect(layout.isSplit).toBe(false);
    expect(layout.cardWidth).toBe(464);
    expect(layout.innerSide).toBeCloseTo(38.4, 1);
    expect(layout.barHeight).toBe(4);
  });

  test('phone 390: card 358, 24 px inside, a 3.2 px top line', () => {
    const layout = signInLayout(390, 844);
    expect(layout.isPhone).toBe(true);
    expect(layout.cardWidth).toBe(358);
    expect(layout.innerSide).toBe(24);
    expect(layout.barHeight).toBeCloseTo(3.2, 5);
  });

  test('the type sizes follow the web tokens at each width', () => {
    expect(typeSizes(1440)).toMatchObject({ label: expect.closeTo(13.69, 2), micro: expect.closeTo(12.7, 2), display: expect.closeTo(24.15, 2), brandTitle: 57.6 });
    expect(typeSizes(768).display).toBeCloseTo(21.56, 2);
    expect(typeSizes(390)).toMatchObject({ label: expect.closeTo(13.02, 2), micro: expect.closeTo(12.03, 2), display: expect.closeTo(20.11, 2) });
  });
});
