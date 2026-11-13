---
name: Transcribey
description: A calm, Apple-like local workspace to turn audio into a transcript and review it line by line.
colors:
  action-blue: "#0066cc"
  action-blue-dark: "#7ec3ff"
  focus-blue: "#0071e3"
  ink: "#1d1d1f"
  ink-dark: "#ffffff"
  muted: "#333333"
  faint: "#6b6b78"
  line: "rgba(29, 29, 31, 0.14)"
  white: "#ffffff"
  ground-light: "linear-gradient(160deg, #e2e5f1, #ebe3f0)"
  ground-dark: "#000000"
  success: "#0b5a34"
  success-quiet: "#e8f5ee"
  warning: "#7a4500"
  warning-quiet: "#fff4e0"
  error: "#912018"
  error-quiet: "#fdecea"
typography:
  display:
    fontFamily: "Inter, 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.4px"
  heading:
    fontFamily: "Inter, 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.19
    letterSpacing: "0.231px"
  body:
    fontFamily: "Inter, 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 1.47
    letterSpacing: "-0.374px"
  small:
    fontFamily: "Inter, 'Noto Sans Thai', system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.47
  code:
    fontFamily: "'JetBrains Mono', monospace"
    fontSize: "0.88em"
    fontWeight: 400
rounded:
  sm: "12px"
  md: "14px"
  lg: "24px"
  pill: "9999px"
---

<!-- Source-aligned design reference. Describes the page rendered from src/transcribey/static. -->

# Design System: Transcribey

## 1. Scope and Identity

Transcribey is one local page: add recordings, make a transcript, check and fix it, download it. The look follows Apple's design language (large quiet type, one blue accent, pill buttons, no decoration without a job). The page is plain HTML, CSS and JavaScript with no build step, so every token here is a CSS custom property in `style.css`.

Source files:

- `static/style.css`: all tokens (`:root`), the dark scheme (`prefers-color-scheme: dark`), and every component.
- `static/index.html`: markup. Each step is a `section` with `data-step` set to `todo`, `current` or `done`.
- `static/app.js`: sets those states, draws the timeline lanes on a canvas, and builds dialogs.
- `static/*.woff2`: the three self-hosted fonts. Notice in `FONTS-LICENSE.txt`.

This document describes what is rendered. It is not a WCAG certification.

## 2. Colors and Surfaces

### Palette

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--accent` | `#0066cc` | `#7ec3ff` | Outline buttons, links, selection, info hover |
| `--btn-grad` | `#1870db` to `#0057b8` | same | Primary button fill |
| `--on-accent` | `#fff` | `#000` | Text on a filled accent |
| `--focus` | `#0071e3` | `#7ec3ff` | Focus ring |
| `--ink` | `#1d1d1f` | `#fff` | Headings and text |
| `--muted` | `#333` | `#d1d1d6` | Secondary text |
| `--faint` | `#6b6b78` | `#bdbdc5` | Metadata, borders on hover |
| `--line` | `rgba(29,29,31,.14)` | `rgba(255,255,255,.2)` | Hairlines and borders |
| `--ok` / `--okbg` | `#0b5a34` / `#e8f5ee` | `#5fd39a` / `#14301f` | Done, All reviewed |
| `--warn` / `--warnbg` | `#7a4500` / `#fff4e0` | `#f2b34c` / `#38290f` | Unsure, warnings |
| `--bad` / `--badbg` | `#912018` / `#fdecea` | `#ff8b80` / `#3a1a17` | Errors, Remove, delete |

Light and dark follow the system setting. There is no manual switch.

### Ground and glass

- Light ground: a two-colour gradient, lavender to pink (`#e2e5f1` to `#ebe3f0`).
- Dark ground: pure black with a 56px grid. The grid fades out from the window centre (solid to 40%, gone by 90%), lines at 10% white.
- Panels are frosted glass: `--glass` fill, `--glass-edge` border, `backdrop-filter: blur(19px) saturate(140%)`, shadow `--lift`. The player bar and the sticky toolbar use a lighter blur (16px).
- Pearl surfaces (play, + line below, player bar buttons) use `--pearl`, and brighten to `--pearl-hover` on hover.
- With `prefers-reduced-transparency: reduce`, glass becomes opaque `--card`.

This is a deliberate exception to the Apple rule of no gradients and no shadows: it applies to surfaces only. Text and controls stay flat.

**Accent has a job.** Blue means an action or the current selection. Status uses green, amber and red, always with words: a chip never carries meaning by colour alone.

## 3. Typography

Inter for Latin text, Noto Sans Thai for Thai, JetBrains Mono for `<code>` chips. All three are self-hosted `.woff2` files (`/inter.woff2`, `/noto-sans-thai.woff2`, `/jetbrains-mono.woff2`), with `unicode-range` so the browser loads a file only when needed. Inter and Noto use `font-display: block` and are preloaded to avoid a flash; JetBrains Mono uses `swap`. Fonts are cached 7 days; everything else is `no-store`.

Body uses Inter stylistic set `ss03` and `-0.374px` tracking.

### Type scale

| Element | Style |
| --- | --- |
| `h1` | 40px / 600 / 1.1, tracking -0.4px; 34px under 640px, 28px under 420px. Dark mode: white to grey fade |
| `h2` (step headings) | 21px / 600 / 1.19. Flex row with the step badge centred |
| Body | 17px / 400 / 1.47 |
| Small, chips text, tags, pills | 14px |
| Counts and tiny labels | 12px |
| `code` chip | JetBrains Mono, 0.88em, on a `--chip` background |

Only four sizes carry hierarchy: 14, 17, 21 and 40. Keep technical terms exactly as written in the UI. Names, file names and commands appear as `<code>` chips.

## 4. Layout and Responsive Behavior

- One centred column: `main` is max **980px**, padded 32px top, 24px sides, 80px bottom.
- Four step sections stack vertically. A step is `todo` (dimmed), `current` (full) or `done`. Steps 3 and 4 stay hidden until lines exist, then both are current.
- Step 3 holds one `details#review` ("Transcript lines"), closed by default. The page never opens it. It closes again when a job ends. A **New** badge pulses once when a run finishes and clears on open.
- Floating player bar at the bottom while a line is loaded: previous, play or pause, next, stop, speed, loop and auto-next.
- Spacing runs in 4px steps (4, 8, 12, 16, 24, 32).

| Breakpoint | Change |
| --- | --- |
| 640px and below | `h1` 34px, controls keep a 44px height, toolbar wraps |
| 419px and below | `h1` 28px |

Touch targets are at least 44px. Compact row controls use 32 to 36px.

## 5. Shapes, Depth and Motion

| Token | Value | Use |
| --- | --- | --- |
| `--pill` | 9999px | All buttons, chips, pills, tags |
| `--r-lg` | 24px | Panels, dialog, drop zone |
| `--r-md` | 14px | Select, info tips |
| `--r-sm` | 12px | Message boxes, Missed speech rows |

- Depth: one glass shadow, `--lift`. The dialog sits on a `--scrim` backdrop.
- Press: buttons scale to 0.95 on `:active`.
- Motion is short (0.1s to 0.15s). The drop-zone waveform animates on drag-over; the timeline lanes redraw live while a run works. `prefers-reduced-motion: reduce` turns animation off.

## 6. Components

### Buttons

| Kind | Style |
| --- | --- |
| Outline (default) | Pill, 1px `--accent` border, accent text, 44px high, 22px side padding. Hover (hover-capable devices only) fills with `--accent` and `--on-accent` text |
| Primary | `--btn-grad` fill, white text. Hover: `filter: brightness(1.2)` |
| Big | 48px high, for **Start transcribing** |
| Pearl | `--pearl` fill, brightens on hover, `--faint` border |
| Danger (`.danger`) | Remove and delete. Hover fills `--badbg` with `--bad` text |
| Link button (`a.btn`) | Step 4 downloads; same look, real links |
| Disabled | 40% opacity |

Focus: a 2px `--focus` ring on `:focus-visible`.

### Controls

- **Select**: native `appearance: base-select` popup, opens downward and flips up only when the list does not fit. Styled scrollbar.
- **Checkbox and radio**: custom drawn, same accent.
- **Info tip `(i)`**: a round button that opens a native `popover` anchored below it (CSS anchor positioning). Used on Language, Quality, Use, names and terms, Use a different model, Show filter and Check for missed speech.
- **Details**: custom chevron, centred on the text.

### Step 1 drop zone

A glass panel with a waveform that animates on drag-over. The highlight clears on `dragleave` only when `relatedTarget` is null, and only for file drags. The Craig `.zip` hint and file types sit inside it as `<code>` chips.

### Person row

Name field is 37.5% wide (220px column) with high-contrast capsules. Long names are cut with an ellipsis and keep a `title` on hover.

### Status chips

| Chip | Look |
| --- | --- |
| `N unsure` | `--warn` on `--warnbg` |
| `All reviewed` | `--ok` on `--okbg` |
| `New` | One pulse, clears on open |

States use these words only: **unsure**, **not reviewed**, **all**, **TH/EN**, **reviewed**. The Show filter lists them in the order all, unsure, not reviewed, TH/EN. A reviewed line hides its tag, reason and underlines.

### Timeline lanes

A canvas, one lane per person. The current lane is outlined; the others are dimmed. Fed by the job status keys `ids` and `spans`.

### Dialog

One styled `<dialog>` replaces `confirm()` and `alert()`: `ask` (two buttons) and `tell` (OK only).

### Messages

`.box` with `ok`, `warn` or error variants. The top box shows only warnings and errors. The GPU found message is a quiet hint under the Use select.

## 7. Do's and Don'ts

**Do**

- Use pill shape for every button, chip and tag.
- Keep one accent colour. Pair every status colour with words.
- Write copy with one idea per line, in plain words.
- Keep Thai and English both readable: test long Thai names and mixed text.
- Add a `--var` token before adding a raw colour.
- Check both light and dark, and the reduced-transparency fallback.

**Don't**

- Don't add a manual theme switch, a second accent, or icon-only meaning without an accessible name.
- Don't use glass or gradients on text or controls. They belong to surfaces only.
- Don't use browser `confirm()` or `alert()`; use `ask` and `tell`.
- Don't put an `<button>` inside an `<a>` (downloads are `a.btn`).
- Don't use glyph characters for save state or upload errors; they are drawn.
- Don't add a build step or an external font or CDN: the page must work offline.

## 8. Known Gaps

- No real logo; the favicon is a placeholder inline SVG.
- Dark placeholder text contrast is about 3.3:1, below the 4.5:1 target.
- The `tell` dialog path has no test.
- Timeline lanes were checked with a faked status, not a real model run.
