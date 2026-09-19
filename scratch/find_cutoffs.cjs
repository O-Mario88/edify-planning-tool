const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  
  const pagesToTest = [
    {
      name: 'CD Country Planning Oversight',
      url: 'http://127.0.0.1:8000/country-planning-oversight/',
      cookie: 'ahnmzx96n6w35y82i7i0v5t7wm4j67y1'
    },
    {
      name: 'PL Team Oversight',
      url: 'http://127.0.0.1:8000/team-planning-oversight/',
      cookie: 'r76l8y4266023i3d12wcqb1uq23a29n7'
    },
    {
      name: 'CCEO My Plan',
      url: 'http://127.0.0.1:8000/my-plan',
      cookie: 'hx53qqqzv3lo7bkiycag1gh2io8opigr'
    }
  ];

  for (const p of pagesToTest) {
    console.log(`\n========================================`);
    console.log(`Testing: ${p.name} (${p.url})`);
    console.log(`========================================`);

    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await context.addCookies([
      { name: 'sessionid', value: p.cookie, domain: '127.0.0.1', path: '/' }
    ]);
    const page = await context.newPage();
    await page.goto(p.url);
    await page.waitForTimeout(1000);

    const issues = await page.evaluate(() => {
      const results = [];
      const tables = document.querySelectorAll('table');
      tables.forEach((table, tIdx) => {
        const titleEl = table.closest('.card, details, section') ? table.closest('.card, details, section').querySelector('h2, h3, h4, h5, summary') : null;
        const tableName = titleEl ? titleEl.innerText.trim().replace(/\n+/g, ' ') : `Table ${tIdx}`;
        
        // Find cells with school names, cluster names, or data-record-title
        const cells = table.querySelectorAll('td, th[scope="row"]');
        cells.forEach(cell => {
          const header = table.querySelectorAll('th')[cell.cellIndex]?.innerText.trim() || '';
          const isSchoolOrCluster = /school|cluster|partner|context/i.test(header) || cell.hasAttribute('data-record-title');
          
          if (isSchoolOrCluster) {
            const inner = cell.firstElementChild || cell;
            const style = window.getComputedStyle(inner);
            const cellStyle = window.getComputedStyle(cell);
            
            // Check if overflowing / cut off:
            // 1. scrollWidth > clientWidth with overflow hidden/clip
            // 2. scrollHeight > clientHeight with overflow hidden/clip
            // 3. ellipsis active
            const isHorizCut = inner.scrollWidth > inner.clientWidth && (style.overflow !== 'visible' || style.textOverflow === 'ellipsis');
            const isVertCut = inner.scrollHeight > inner.clientHeight && style.overflow !== 'visible';
            const cellCut = cell.scrollWidth > cell.clientWidth && (cellStyle.overflow !== 'visible' || cellStyle.textOverflow === 'ellipsis');
            
            if (isHorizCut || isVertCut || cellCut || inner.scrollWidth > cell.clientWidth) {
              results.push({
                table: tableName,
                header,
                text: cell.innerText.trim().replace(/\n+/g, ' '),
                cellWidth: cell.clientWidth,
                cellScrollWidth: cell.scrollWidth,
                innerWidth: inner.clientWidth,
                innerScrollWidth: inner.scrollWidth,
                innerHeight: inner.clientHeight,
                innerScrollHeight: inner.scrollHeight,
                whiteSpace: style.whiteSpace,
                overflow: style.overflow,
                textOverflow: style.textOverflow,
                isHorizCut,
                isVertCut,
                cellCut
              });
            }
          }
        });
      });
      return results;
    });

    console.log(`Found ${issues.length} potential cutoff issues:`);
    issues.forEach((iss, i) => {
      console.log(`[${i + 1}] Table: "${iss.table}" | Header: "${iss.header}"`);
      console.log(`    Text: "${iss.text}"`);
      console.log(`    Cell W: ${iss.cellWidth} (scroll ${iss.cellScrollWidth}), Inner W: ${iss.innerWidth} (scroll ${iss.innerScrollWidth}), H: ${iss.innerHeight} (scroll ${iss.scrollHeight})`);
      console.log(`    whiteSpace: ${iss.whiteSpace}, overflow: ${iss.overflow}, textOverflow: ${iss.textOverflow}`);
    });

    await context.close();
  }

  await browser.close();
})();
