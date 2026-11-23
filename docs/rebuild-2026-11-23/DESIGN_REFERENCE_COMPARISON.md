# Design reference comparison

Each page was captured from the running Next.js app (`localhost:3095`, on the Go gateway) at its reference's size and compared by eye. No pixel-difference tool was used. The figures and names are the private development database's, so they differ from the sample values in the references by design. The old Django pages on `localhost:8011` were not changed.

| Reference | Page | Now matches | Differences that remain, and why |
|---|---|---|---|
| 1 | Cluster desktop | Band with actions top right, icon tabs, horizontal figures, SSA donut with domain table, analytics tabs, readiness legend, activities, attendance, insights, member table header, recommended actions | Not Assessed instead of 0.00. Drawn hills instead of a landscape photo. The legend has no In Progress state because the system records none. Visit Lock, Planning Readiness and Responsible Staff moved into each opened row. |
| 2 | School desktop | Icon tile, badges, name, facts, button row, Actions menu, icon tabs, the three-column card grid, trend, GPS card | School icon replaces the photo, as asked. Tabs follow the written brief (Participation, Academic, Stories). Period and extra figures sit behind the small `+` button. |
| 3 | School Core tab | Band with readiness and the Champion checks, five figures, Package, Participation, Insights, Interventions, Outcomes, Recommended Support | No readiness percentage, because Go does not calculate one; the band shows the three real Champion checks. Add Intervention and Assign Package are not shown because no such form exists; the card links to Core School Oversight. |
| 4 | Route desktop | Header, figures, configuration column, map toolbar and stack, timeline itinerary, bottom row aligned under the map | No Terrain button because no terrain source is configured. Traffic reads Unavailable without a Google key. The legend shows pin groups, not Open/Slow/Heavy, and Road Conditions counts reports rather than distance, because no road-condition data exists. Route Options fill after Compare, because each option is an audited calculation. Schools Near Your Route stays as a closed row under the page. |
| 5 | Route phone | Header, three figures, date and place fields, Map/List, Recommended Route card, map controls, draggable sheet, two actions | Same data limits as reference 4. |
| 6 | School phone | Back and Actions row, icon tile, six action tiles, tabs with More, four figures across, trend beside GPS, Operations beside Loans, intervention table, Needs Attention | School icon replaces the photo. Accuracy and Last Verified are hidden in the small phone GPS card. |

There is no phone reference for the Cluster Profile, so its phone layout follows the desktop design and the School phone reference.

Desktop, phone, tablet and dark mode were each reviewed by eye on 2026-11-23.
