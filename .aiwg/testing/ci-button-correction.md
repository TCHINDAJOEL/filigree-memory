# CI button width correction

## Failure
Linux browser job: D4 (768px) `#new-project` width 23.6875 < 24. 17 passed, 1 failed, 10 not run (log: `.runtime/ci-browser-failure.txt`).

## Diagnosis (from code only)
- At 768px only the `@media(min-width:651px)` rule applies to `.sidebar-add`. The `max-width:650px` block, which sets `min-width:40px`, does not.
- The 651px rule gave the button `height:24px` and `padding:0 6px`, with no `min-width`. Its width was therefore the "+" glyph width plus 12px of padding, so it depended on font metrics and rounded to 23.69px on Linux.
- The 375px layout is covered by the 650px block (40x40, `flex:0 0 auto`) and is unchanged. 1440px uses the base rule and is unchanged.

## Change (filigree/static/styles.css, `min-width:651px` block only)
`.sidebar-add{top:-5px;box-sizing:border-box;flex:0 0 auto;min-width:28px;min-height:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:20px;padding:0 6px}`
- The button now has a 28px minimum width and height, so font and rounding differences can't push it under 24.
- `flex:0 0 auto` stops it shrinking.
- `top` moves from -3px to -5px so the taller button stays vertically centred.
- No markup, test, or threshold changes.

## Verification
NOT RUN. Bash was denied by the permission mode when I tried to run the full Playwright suite (28 tests). The wheel build and `verify_package` were also not run.
Nothing is verified locally yet, and Linux CI has not been re-run.
