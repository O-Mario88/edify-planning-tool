<!--
  Edify PR template. Three sections. Keep it tight.
-->

## What
<!-- 1-3 bullets. What changes and why now. -->

## How to test
<!-- The exact route, the exact role, the exact thing the reviewer
     clicks to verify. If there's no UI surface, link the test that
     proves it. -->

## Risk
<!-- Pick one: low / medium / high. If medium or high, write 1 line
     on the blast radius and 1 line on the rollback plan. -->

---

- [ ] `npm run ci` passes locally
- [ ] Touches a money-handling code path? If yes, the weekly-fund engine
      tests still pass and I added a new one for the change.
- [ ] Touches auth, cookies, or middleware? If yes, I re-verified the
      role-restricted routes still gate correctly.
