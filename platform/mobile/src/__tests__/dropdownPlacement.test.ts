import { placePanel, roomToMake } from '../ui/dropdownPlacement';

const PHONE = { width: 375, height: 812, bottomInset: 34 };
// A row's Actions button near the right edge, high on the screen.
const ACTIONS = { x: 265, y: 442, width: 79, height: 24 };

describe('placePanel', () => {
  test('drops the panel down below the button, never over it', () => {
    const place = placePanel(ACTIONS, PHONE, { align: 'end', minWidth: 176 });

    expect(place.top).toBe(ACTIONS.y + ACTIONS.height + 6);
    expect(place.top).toBeGreaterThan(ACTIONS.y + ACTIONS.height);
  });

  test('lines the right edge up with the button for end alignment', () => {
    const place = placePanel(ACTIONS, PHONE, { align: 'end', minWidth: 176 });

    expect(place.right).toBe(PHONE.width - (ACTIONS.x + ACTIONS.width));
    expect(place.left).toBeUndefined();
    expect(place.minWidth).toBe(176);
  });

  test('stretches to the field width, at least the menu minimum', () => {
    const field = { x: 39, y: 348, width: 297, height: 40 };
    const narrow = { x: 16, y: 259, width: 67, height: 32 };

    expect(placePanel(field, PHONE, { align: 'stretch', minWidth: 176 }).width).toBe(297);
    expect(placePanel(narrow, PHONE, { align: 'stretch', minWidth: 176 }).width).toBe(176);
  });

  test('keeps a stretched panel off the right edge of the screen', () => {
    const nearEdge = { x: 300, y: 100, width: 60, height: 32 };

    const place = placePanel(nearEdge, PHONE, { align: 'stretch', minWidth: 176 });

    expect((place.left ?? 0) + (place.width ?? 0)).toBeLessThanOrEqual(PHONE.width - 8);
  });

  test('stops above the bottom navigation and scrolls inside instead', () => {
    const place = placePanel(ACTIONS, PHONE, { align: 'end', minWidth: 176 });

    expect(place.top + place.maxHeight).toBeLessThanOrEqual(PHONE.height - PHONE.bottomInset - 56);
  });
});

describe('roomToMake', () => {
  test('asks for no scroll when the panel fits below the button', () => {
    expect(roomToMake(ACTIONS, 98, PHONE)).toBe(0);
  });

  test('asks the page to scroll up by what is missing near the foot', () => {
    const lowButton = { x: 265, y: 680, width: 79, height: 24 };

    const pixels = roomToMake(lowButton, 98, PHONE);

    const floor = PHONE.height - PHONE.bottomInset - 56 - 8;
    expect(pixels).toBe(lowButton.y + lowButton.height + 6 + 98 - floor);
  });
});
