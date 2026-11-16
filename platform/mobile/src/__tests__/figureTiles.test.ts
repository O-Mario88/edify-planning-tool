import { figureIcon, tileColumns } from '../ui/page/figureTiles';

describe('figure tiles', () => {
  it.each([
    ['Total Core Schools', 'school'],
    ['Schools in Clusters', 'school'],
    ['Total Clusters', 'cluster'],
    ['Total Distance', 'route'],
    ['Overdue Tasks', 'alert'],
    ['Without Current SSA', 'alert'],
    ['Total Budget', 'money'],
    ['Partner Pending Schedule', 'people'],
    ['Visits Scheduled', 'calendar'],
    ['Activities Completed', 'check'],
    ['Average Cluster SSA', 'chart'],
    ['Data Cleanliness', 'chart'],
  ])('draws %s with the %s icon, as the web', (label, icon) => {
    expect(figureIcon(label)).toBe(icon);
  });

  it('keeps two a row on a phone and spreads wide rows evenly, at most five', () => {
    expect(tileColumns(10, 390)).toBe(2);
    expect([4, 6, 8, 10].map((n) => tileColumns(n, 1200))).toEqual([4, 3, 4, 5]);
  });
});
