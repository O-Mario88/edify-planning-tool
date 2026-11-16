import { describe, expect, it } from 'vitest';

import { figureIcon } from './figureIcon';

describe('figureIcon', () => {
  it.each([
    ['Total Core Schools', 'school'],
    ['Schools in Clusters', 'school'],
    ['Total Clusters', 'cluster'],
    ['Total Distance', 'route'],
    ['Total Travel Time', 'clock'],
    ['Visits Scheduled', 'calendar'],
    ['In My Plan', 'calendar'],
    ['Activities Completed', 'check'],
    ['Overdue Tasks', 'alert'],
    ['Without Current SSA', 'alert'],
    ['Cost Blocked', 'alert'],
    ['Total Budget', 'money'],
    ['Partner Pending Schedule', 'people'],
    ['Trainings Scheduled', 'training'],
    ['Average Cluster SSA', 'chart'],
    ['Weakest Intervention', 'chart'],
  ])('draws %s with the %s icon', (label, icon) => {
    expect(figureIcon(label)).toBe(icon);
  });

  it('falls back to the chart for a label it does not know', () => {
    expect(figureIcon('Data Cleanliness')).toBe('chart');
  });
});
