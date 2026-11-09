# Section library design checklist (Story 17.7)

The rules every section and variant in `files/renderer` (and the shared `files/common` layout pieces) keeps, so a
site built from the FrontendSpec without the engine looks designed in every theme preset, light and dark. They come
from Taste Skill's page rules (MIT, see `docs/research/design-skills.md`), used as rules only.

How it is checked: the unit tests (`tests/test_fonts_and_variants.py`, `tests/test_design_tone.py`) cover what the
generator controls (fonts, dark-mode colours, variant typing, the headline length warning, tone tokens);
`scripts/design-check.mjs` measures a built site at 390 / 768 / 1440 px, light and dark. `make design-check-fixture`
builds the section-library fixture in every preset (`ARGS="--combos"`: in six tone, font and preset combinations,
Story 20.3) and checks the measured rules below; screenshots under `.data/shots/`. Re-run it when a section or
variant changes.

| Rule | How the library keeps it | Measured (fixture, 5 presets × 6 pages × 3 widths × 2 schemes) |
|---|---|---|
| One accent per page | `primary` is the only accent colour (eyebrows, icons, highlighted plan, buttons). The `accent` token is only shadcn's hover tint | by review |
| One radius system | Every corner is a `rounded-*` step derived from the theme's `--radius` (`globals.css`); no fixed pixel radii | by review |
| Two font families at most | `--font-display` (headings) and `--font-body`; both from the theme, loaded from `@fontsource` | the theme's 1–2 families in every view, and the same families report `loaded` in `document.fonts` |
| Five type sizes at most per page | `text-sm`, `text-base`, `text-lg`, `text-2xl` and one hero size (`headlineClass` / `displayClass`); stats, figures, prices, statements and the vertical hero label use `text-2xl` or the hero's size | 4–5 per view (the hero is the only size that changes with the width: 24–60 px) |
| Body line length 45–75 characters | Paragraphs are `max-w-prose` (65ch) | ≤ 75 everywhere (longest 41 in the fixture's copy); see deviations for the 45 minimum |
| Hero headline two lines at most at 390 / 768 / 1440 px | `headlineClass` sizes the headline by length; wide faces and capitals shrink the hero sizes (`--hero-<step>`, `display_scale` from `Font.width`, case and tracking, Story 20.3); the validator warns above 50 characters (`FE_DESIGN_RULE`) | 1–2 lines in every view; 42–52-character headlines in Poppins and Playfair Display also stay at 2 |
| Primary CTA above the fold | The hero's first link is its primary CTA | above the fold in every view |
| Nav ≤ 80 px | Header `h-16` (64 px), one line; the menu collapses below `md` | 65 px |
| Off-black / off-white in dark mode | `frontend_theme.py` clamps the dark palette to `#0a0a0a` / `#fafafa` | body `#0a0a0a`…`#14122f` (tinted per preset) with `#fafafa` / `#f8fafc` text; never `#000` / `#fff` |
| Motion on transform and opacity only, with a `prefers-reduced-motion` fallback | The only library motion is the CardGrid hover lift (`transition-transform`, `motion-reduce:` off); colour changes are instant | by review |

## Videos (Epic 31)

Sample videos come through the library only (`Video` section, the hero's `backgroundVideo`, the tree's `VideoEmbed` /
`BackgroundVideo` data components); raw `video` / `iframe` elements stay removed from designed pages.

| Rule | How it is kept |
|---|---|
| No request to YouTube before the user presses play | `VideoEmbed` is a facade: the poster (YouTube's thumbnail), a play button, the title and the credit; the `youtube-nocookie.com` iframe is mounted on click only; without JavaScript the facade is a link to the video |
| A moving background is polite | `BackgroundVideo`: muted, `playsinline`, looped, the poster first; a visible pause / play button; paused and still under `prefers-reduced-motion` and when the browser asks to save data; the hero's text keeps its contrast over a `bg-background/70` scrim |
| Every video is credited | "<title> · <channel> on YouTube" or "Video by <name> on Pixabay", linked, under the player or in the hero's corner; the README lists every video |
| Nothing is copied | YouTube plays in its player; Pixabay files are linked; only Pixabay posters are stored (its images may not be hotlinked) |

## Designed pages (Epic 21)

A page may be an element tree the drafting engine designed (`pages[].tree`, `layout.chrome`, `footerTree`),
rendered by `renderer/tree/TreeRenderer.tsx`. The rules above still apply; the tree rules (`frontend_spec/trees.py`,
checked by the validator and repaired by `fix_trees`) keep what a free hand could break:

| Rule | How it is kept |
|---|---|
| Colours only through theme tokens | Palette classes (`bg-emerald-500`) and arbitrary colour values (`text-[#fff]`) are stripped with a note; raw colours in the page CSS are a warning |
| Nothing fixed, nothing hidden | `fixed` is stripped on pages (the chrome may stick); `script`, `iframe`, `style`, `form`, `input`, `video` are removed; `animate` only moves opacity, translate and scale under `html[data-motion="on"]`, revealed by `MotionRoot` like sections |
| One `h1`, images with alt, links that exist | Warnings; a foreign image source becomes a placeholder asset; a link to an unknown page goes home |
| Bounded | ≤ 2000 nodes, ≤ 24 levels (errors); unknown node types are unwrapped, their children kept |
| Page CSS scoped to its page | Every selector is prefixed with `[data-page="<id>"]`; `@keyframes` keep their names; imports, external and data URLs are dropped |
| Data from the contract or a collection | `tree_bindings.bind_tree` binds containers, figures and writes; a page whose tree still fails keeps its sections |

The fixture's `/designed` page exercises elements, a Tabs primitive, icons, a Faq section node, `Metric` and
`Chart`, a `CollectionStrip` and a `CollectionBrowser` with controls; `make design-check-fixture` measures it with the
other pages. Known deviations on it: `font-mono` on a site without a mono font reports `ui-monospace` as not loaded
(the tree prompt forbids `font-mono` unless the direction names one); its two-line headline wraps to 3–4 lines at
390 px in `text-5xl` (the prompt asks for `text-4xl md:text-6xl` or smaller).

## Variants

| Variant | Where | Values |
|---|---|---|
| `background` | every content section | `default`, `muted`, `primary` (the `surface-inverse` token scope swaps primary and background, so cards, muted text and buttons keep contrast), `image` (`backgroundImage` under a scrim in the page colour) |
| `variant` | Hero | `split` (text beside the image from 1024 px), `centered`, `banner` (full width; the image behind the text, or the primary colour) |
| `cardStyle` | Features, Testimonials, Pricing, Stats, CardGrid | `outline` (shadcn card), `filled` (muted surface, no outline), `plain` (no surface) |
| `background` on CallToAction | the panel | `primary` by default, `default` = outlined panel |
| `variant` (Story 20.2) | Hero | also `stage` (the image is the first screen, text on its lower edge), `type` (oversized headline, `displayClass`, no image), `stacked` (full-width headline, text and actions in a row, wide image), `collage` (text beside 2–4 images; fewer → `split`, validator warning), `vertical` (the eyebrow as a rotated label at the headline's size, horizontal on phones) |
| `form` (Story 20.2) | Features, Testimonials, Stats | Features `cards` / `list` (numbered rows) / `ledger` (hairline rows) / `alternating` (image and text rows; without item images → `list`, validator warning); Testimonials `cards` / `quote` / `strip` (a keyboard-scrollable row); Stats `cards` / `figures` (no boxes, accent rule) / `inline` |
| `featured` (Story 20.2) | CardGrid | the first record spans two columns from 640 px |
| `rhythm` (Story 20.2) | a page | `uniform`; `alternate` (sections without a background alternate page colour and muted, written into `site.json`); `dividers` (a hairline between sections) |
| `form` (Story 20.8) | Steps, Timeline, Team, PriceList, Location, Comparison, Statement | Steps `numbered` / `horizontal` / `connected`; Timeline `vertical` / `alternating`; Team `grid` / `list` / `portraits`; PriceList `menu` / `columns` / `cards`; Location `split` / `card` / `band`; Comparison `table` (scrolls sideways in a focusable region) / `cards`; Statement `large` / `quote` / `band` |

## Tone tokens (Story 20.3)

Optional theme fields; without them a site looks as before. `orchestrator/design_tone.py` maps a direction's five
tone scales to them (the table is in its docstring).

| Token | Drawn as |
|---|---|
| `typography.headingWeight`, `headingCase`, `tracking` | the `heading` utility (`globals.css`) on hero and section headings: `--heading-weight` (600), `--heading-tracking` (−0.025em; `wide` with capitals), `--heading-case`. Capitals only on display headings (h1, h2), never on statements or body text |
| `typography.ratio` | the display steps of the type scale (`--text-2xl` … `--text-9xl` in `@theme`) and the hero sizes: `tight` smaller, `dramatic` larger (on the hero only the steps of short headlines and the `type` layout, `6xl` and up: longer headlines already fill two lines) |
| `surface` | cards: `outline` (shadcn's hairline ring), `flat` (no ring, no shadow), `raised` (soft shadow instead of the ring); unlayered rules in `globals.css`, the `filled` and `plain` card styles keep their own look |
| `colorArea` | `site.json` per page: `minimal` (call-to-action panels muted, colour on buttons), `block` (one anchor section in the primary colour: the first call to action, else the last content section), `bold` (also the hero). Sections that name a background keep it |

Fonts: eight faces with more character joined the set (Fraunces, Instrument Serif, Newsreader, Bricolage Grotesque,
Syne, Archivo, Unbounded, Familjen Grotesk; OFL). Each bundled font has a rough `width` against Inter; wide faces
(Unbounded, Syne, Montserrat, the monospace faces) shrink the hero sizes so headlines keep to two lines.

## Directions and app pages (Story 20.4)

A direction card sets the theme, tone tokens, hero layout, section forms and rhythm for every page, and composes the
home page from the drafted sections; it adds no new drawing rules. In a dynamic app the data pages (DataTable, List,
DetailView, Form, ActionBar, CardGrid on the API) keep their structure and take the direction through the same
tokens: section headings and the record title use the `heading` utility and the heading face, record panels are
cards (so `surface` applies), and colour, radius and density come from the theme. They are measured on the mock API
(`make design-check-fixture --spec <dynamic spec> --backend <its BackendSpec>`); a page without a hero has no
"CTA above the fold" measurement.

## Icons (Story 20.5)

- **One set per site**, from `theme.icons` (`lucide` / `phosphor` / `none`), with a weight (Lucide draws thin to bold
  as stroke widths 1 / 1.5 / 2 / 2.5; fill and duotone are Phosphor's) and a treatment (`plain`, or `tile`: a 40 px
  rounded square in the muted tone). Items carry a reference or an intent; the generator resolves it to the site's set
  (`frontend_spec/icons.py`) and `src/components/renderer/icons.ts` imports only the icons the site uses.
- **Where:** Features (above a card's title, in place of the list numeral, before a ledger title), Stats (heading a
  card, by a figure's label, before an inline value), Pricing (by a plan's name). Never on headings. The library's own
  marks (checks, minus, contact details, opening hours) are drawn in the site's set through `Icon glyph`.
- **Size and meaning:** 1.25 × the text they sit with, `aria-hidden` (the text carries the meaning), the primary
  colour. With `none`, content icons and decorative marks are left out and lists keep their numbers; checks stay.

## Motion (Story 20.6)

- **Only when it is safe:** the page's inline script sets `html[data-motion="on"]` when JavaScript runs and the
  visitor has not asked for reduced motion, and removes it if the page has not come alive within 3 s. Every rule is
  scoped to it, so without JavaScript or with reduced motion every element is in its final state.
- **Presets, not per-site code:** `theme.motion.feel` picks a spring preset (`orchestrator/frontend_motion.py`):
  durations 120–800 ms, easings as CSS `linear()` (surfaces overshoot ≤ 2%, marks ≤ 15%), `cut` as steps.
- **Three baseline motions:** buttons press to 0.97; the Tabs indicator grows with the feel (Faq keeps the base
  accordion's height animation); the hero enters headline → text → actions → image, one stagger apart, ≤ 600 ms.
- **Reveals by content:** below the hero each section reveals once when 15% (or 240 px) of it is visible:
  headings, cards, list items, figures, quotes, images and tables rise or slide in with the feel, followers one
  stagger apart (at most five), images settle from 1.08 scale; stats count up.
- **One signature moment:** `countUp` (longer count), `headlineRise` (the hero headline rises from a mask),
  `imageUnmask` (the hero image unmasks from the side), `indicator` (navigation links underline on hover and for the
  current page).
- **Properties:** `opacity`, `translate`, `scale`; `clip-path` for the two signature masks only.
- **Measured:** `make design-check-fixture ARGS="--motion"`: with motion on, the call to action is fully visible in
  under 1 s and nothing is left transparent or displaced after scrolling; with JavaScript off nothing is hidden.

## App kit (Story 22.4)

The dynamic app flow's kit (`files/dynamic/app/`) is one product UI, not designed pages: the direction sets only
theme tokens (colours, fonts, radius, density), the kit sets everything else. `make design-check-app` plans an app
from an example BackendSpec and outline (no engine), builds it and measures every screen at 375 and 1440 px, light and
dark, on the mock API (`ARGS="--app two-entity:project-tracker"`; screenshots under `.data/shots/design-check-app/`).

| Rule | How the kit keeps it | Measured (flashcards 12 screens, project tracker 9; 375 / 1440 px × light / dark) |
|---|---|---|
| One shell | `AppShell`: the sidebar (icons, collapsible to icons, a sheet on phones), a 56 px top bar with breadcrumbs and the theme switch; every screen is `max-w-6xl` with one gap (`gap-8` between blocks, `gap-4` inside) | top bar 56 px in every view |
| One heading per screen | A list page's first list, a record's name, a form's title or the page title is the `h1` (`text-2xl`); lists in tabs or on the dashboard are `h2` (`text-lg`); a tab's list keeps its heading for screen readers only | one `h1`, on one line, in every view |
| Five type sizes at most | `text-xs` (badges, hints), `text-sm` (tables, labels), `text-lg` (sub-headings), `text-2xl` (headings) and `text-3xl` for dashboard figures only | 2–5 per view (12, 12.8, 14, 18, 24, 30 px across all views; the 12.8 px is the base's small button) |
| Readable records | Parents by name (linked to their page), dates in the reader's locale, enums as badges, numbers grouped with tabular figures, empty values as a dash; a table's first column links to the record | by review |
| Every state | Lists and records: skeletons while loading, an empty state (with "Add" when the list can create), an error state with "Try again"; figures: a skeleton, "No data yet" for an empty chart | by review (mock data: lists full; the 22.5 / 22.6 forms add their own states) |
| Keyboard | Row actions in a menu (`dropdown-menu`: Enter / Space opens, arrows move, Escape closes, focus returns); confirms in `alert-dialog`, forms in `dialog` (focus trapped, Escape closes); the sidebar toggles with ⌘B / Ctrl+B | by review |
| Actions follow the record | Row and record actions show only what `allowedActions` lists (`allowed()` in `app.ts`); errors show the contract's message, on the field when the error names fields | `tests/test_app_screens.py`; by review |
| Density | `theme.density: "compact"` tightens table rows; the rest of the scale stays | by review |
| Off-black / off-white in dark mode | The theme's dark palette (as for sites) | body `rgb(10, 15, 27)` / `rgb(248, 250, 252)` |

### Forms (Story 22.5)

`make design-check-app ARGS="--app tests/fixtures/app-forms/backend.json:tests/fixtures/app-forms/outline.json"`
plans the form fixture (a venue and its bookings: every field kind, help, a unit, a unique name) and reports each
form view's `form` metrics in `report.json`.

| Rule | How the kit keeps it | Measured (venue fixture, `/venues/new`, `/venues/[id]/edit`, `/venues/[id]/bookings/new`; 375 / 1440 px × light / dark) |
|---|---|---|
| The right input per kind | `form/FieldInput.tsx`: dates in a calendar popover (shown in `project.locale`, sent `YYYY-MM-DD`), date-times a calendar and a time (ISO 8601 with the offset), enums a segmented control (≤ 3 short values), radios (≤ 5) or a Select, booleans a switch beside its label, numbers with the contract's `min` / `max` and a step by type, a currency prefix or unit suffix, text areas with a count, typed e-mail / URL / phone inputs, passwords with show / hide | `nativeDateInputs` 0 in all 16 form views; `tests/test_app_forms.py` |
| Labels and help | Every input has its label (`FieldLabel htmlFor`; radios and the segmented control an `aria-label`); required fields marked `*`; the outline's `help` under the field, replaced by the error when there is one | `unlabelled` empty in every form view (primitives' hidden inputs excluded); controls 32 px high |
| Two columns when there is room | The form is a container (`@container`): short fields share a row from 32 rem (`@lg:grid-cols-2`), text areas and a lone field take the full width; one column on phones and in narrow dialogs | `columns` 2 at 1440 px, 1 at 375 px (6- and 11-field forms) |
| One clear submit | Cancel (ghost) and Submit; a spinner and `aria-busy` while saving; an edit form submits only what changed and its Submit stays disabled until something does | `tests/test_app_forms.py`; by review |
| Errors on the field | 422 `details[].loc` and a 409's `details.fields` (a unique name) go under their field (`setError`); anything else is a toast with the contract's message | `tests/test_app_forms.py`; by review |
| Never an id (Story 22.6) | A parent the page knows comes from the route (hidden); any other is a picker (`form/ReferenceField.tsx`): a combobox on the parent's list showing names, searched on the server when the list has search, the chosen one loaded by its `get`; lists and details show parents by name, never the id | `tests/test_app_pickers.py`; the app walk picks a parent on each edit form |
| No sideways scroll, nothing clipped | Inputs are `w-full`; every field may shrink below its content (`min-w-0`: a long date truncates in its button, the date-time row shrinks the date, not the time); a clear button sits beside its picker | `overflowX` false in all 36 views; `clipped` (controls past the form's edge, which the card would hide) empty in all 16 form views since 22.6 (it found the date-time row widening the 375 px column); 2–5 type sizes per view |

### Plugins (Story 22.7)

The plugins' screens are the kit's (`templates/plugins/<name>/frontend/files/`), on the same scale and tokens.

| Rule | How the kit keeps it | Checked |
|---|---|---|
| Sign-in is one card | Sign-in and sign-up: a centred card (`max-w-sm`) with the form kit, a link to the other, the demo accounts under it; the top bar shows Sign in / Sign up, or the account (initials, e-mail from `sm`, role, Sign out) | `scripts/plugin-walk.mjs`; by review |
| Only what the user may do | Navigation, sections and "New" a user cannot use are hidden (`app.access`); a page behind sign-in goes to sign-in and back after; a page the role cannot use says so; record actions follow `allowedActions` (a transition shows only from a state it may leave) | `tests/test_app_plugins.py`; the plugin walk |
| Uploads show what happens | A dashed drop zone (click, keyboard or drop), the size limit, a progress bar while sending, the image's preview, Replace and Remove; a refused type or size says why under the field | the plugin walk (an organizer's cover) |
| A payment is never a dead end | Pay leaves for the provider and comes back to a card that follows the payment (spinner, then paid, failed or canceled, each with its next step) and links back to the record | the plugin walk (mocks and the fake provider live) |
| Links are chips | A record's many-to-many links as chips linked to their page, each with its remove button; a picker and Add under them | the plugin walk |

## Deviations

- **45-character minimum:** a full-width paragraph on a 390 px phone holds about 40 characters at 16 px. The
  library caps the maximum (`max-w-prose`) and accepts shorter lines on phones.
- **shadcn primitives keep their own motion and chips:** the pinned base's button (`transition-all`), accordion and
  sheet animations are not edited (they belong to the base, `make frontend-base`). The library's own badges use the
  `text-sm` step instead of the primitive's 12 px so a page stays at five sizes.
- **Figures and statements stay at `text-2xl` (Story 20.2, 20.8):** a larger number or statement would add a sixth
  size on pages with a hero; they differ from cards by structure (no boxes, an accent rule, the heading face and
  weight), not by size. Measured: the first figures draft at `text-5xl` gave 6 sizes on the stage page at 1440 px.
- **The `type` hero is not cropped at the edge:** cropping display type hurts reading on phones; it is set as large
  as the two-line rule allows instead.
- **Tabs indicator grows rather than slides (Story 20.6):** the base's tabs draw their indicator per trigger; a
  sliding one would mean editing the primitive. Faq keeps the base accordion's own height animation.
- **UI chrome stays Lucide (Story 20.5):** the menu button, theme toggle and error alert are controls from the base,
  like the shadcn primitives; only content icons and the library's marks follow the site's set.
- **Image backgrounds are faint until Epic 15:** placeholder assets are pale gradients, so `background: "image"` and
  the banner's backdrop barely show under the scrim. Real images (Epic 15) make them visible; the scrim keeps text
  readable either way.
