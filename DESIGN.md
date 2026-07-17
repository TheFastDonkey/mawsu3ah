---
name: الموسوعة الكبرى لأفضل طبعات الكتب
description: A community catalog of trusted physical Arabic book editions — scholarly, lightweight, and restrained.
colors:
  bg: "#f6faf6"
  bg-dark: "#171008"
  surface: "#ffffff"
  surface-dark: "#251e15"
  ink: "#0d0d0d"
  ink-dark: "#f6f1eb"
  muted: "#4d4d4d"
  muted-dark: "#ada397"
  accent: "#067132"
  accent-dark: "#d79628"
  accent-hover: "#005b16"
  accent-hover-dark: "#eba941"
  accent-light: "#def1e1"
  accent-light-dark: "#3a2b16"
  border: "#c9d0ca"
  border-dark: "#3a3128"
  error: "#c53637"
  error-dark: "#f2716a"
  error-bg: "#ffe7e4"
  error-bg-dark: "#402624"
  success: "#c8e8cd"
  success-text: "#005820"
  warning: "#f7e2b8"
  warning-text: "#916a00"
typography:
  display:
    fontFamily: '"Amiri", Georgia, serif'
    fontSize: "clamp(2.25rem, 6vw, 4rem)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: '"Amiri", Georgia, serif'
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.2
  title:
    fontFamily: '"Noto Sans Arabic", system-ui, sans-serif'
    fontSize: "1.25rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: '"Noto Sans Arabic", system-ui, sans-serif'
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: '"Noto Sans Arabic", system-ui, sans-serif'
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
rounded:
  sm: "0.25rem"
  md: "0.375rem"
  lg: "0.5rem"
  full: "9999px"
spacing:
  xs: "0.25rem"
  sm: "0.5rem"
  md: "1rem"
  lg: "1.5rem"
  xl: "2rem"
  2xl: "3rem"
  3xl: "4rem"
  4xl: "5rem"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0.625rem 1.25rem"
    typography: "{typography.label}"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "0.625rem 1.25rem"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.625rem 1.25rem"
  button-secondary-hover:
    backgroundColor: "{colors.accent-light}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.625rem 1.25rem"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.625rem"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "1.5rem"
  badge-default:
    backgroundColor: "{colors.accent-light}"
    textColor: "{colors.accent}"
    rounded: "{rounded.full}"
    padding: "0.125rem 0.625rem"
  alert-info:
    backgroundColor: "{colors.accent-light}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0.75rem 1rem"
---

# Design System: الموسوعة الكبرى

## 1. Overview

**Creative North Star: "The Scholar's Desk"**

The interface feels like a clean, well-lit desk in a community library: paper-white surfaces, dark ink type, and one quiet green stamp that marks trusted actions. Every element is tuned for readers who are looking for a specific edition, comparing versions, or approving a contribution. There is no marketplace noise, no ornamental frames, and no dense dashboard metricry. The system favors clarity over decoration, state visibility over visual flourish, and lightness over weight.

This is a **community catalog**, not a campaign site. Color is reserved for action and status; most of the page is neutral so the books themselves remain the focus. The Arabic serif `Amiri` gives headings the dignity of a title page, while `Noto Sans Arabic` handles body text and UI labels with modern neutrality.

**Key Characteristics:**
- Restrained palette: tinted neutrals with a single green accent in light mode, shifting to warm olive/gold in dark mode.
- RTL-first, with generous line-height and a capped measure for prose.
- Stacked-paper depth: cards and suggestions sit slightly above the page with a diffuse shadow.
- Refined utility: consistent 6px radius, solid buttons, bordered form fields, clear focus rings.
- Motion is state-only: 150ms color/border/shadow transitions, disabled under `prefers-reduced-motion`.

## 2. Colors

The palette is intentionally quiet. Light mode reads as fresh paper with a green accent; dark mode flips to a warm, low-light reading room with golden accents. The two themes are not simple inversions — the accent hue shifts from green (150) to olive-gold (75) so the dark theme never feels like a cold, generic "dark mode."

### Primary
- **Olive Trust** (`#067132` / oklch(48% 0.13 150)): Primary actions, active states, expert badges, and the hero kicker. Used sparingly — it is the stamp of trust, not the wallpaper.
- **Olive Trust Hover** (`#005b16` / oklch(40% 0.14 150)): Button and link hover states. Darker and slightly more saturated for clear feedback.
- **Olive Trust Tint** (`#def1e1` / oklch(94% 0.03 150)): Subtle backgrounds for alerts, hidden-comment states, and secondary-hover fills.

### Neutral
- **Pressed Paper** (`#f6faf6` / oklch(98% 0.006 150)): Page background. A near-white with a whisper of green, not cream or beige.
- **Rag White** (`#ffffff` / oklch(100% 0 0)): Card, input, and suggestion-list surfaces.
- **Lampblack** (`#0d0d0d` / oklch(16% 0 0)): Body text and primary ink.
- **Ash Ink** (`#4d4d4d` / oklch(42% 0 0)): Secondary text, metadata, stat labels, and placeholder hints.
- **Ledger Line** (`#c9d0ca` / oklch(85% 0.01 150)): Borders, dividers, and card outlines.

### Dark Theme
- **Night Desk** (`#171008` / oklch(18% 0.02 70)): Dark page background.
- **Dark Rag** (`#251e15` / oklch(24% 0.02 70)): Dark card/surface background.
- **Candle Ink** (`#f6f1eb` / oklch(96% 0.01 70)): Dark-mode body text.
- **Warmed Ash** (`#ada397` / oklch(72% 0.02 70)): Dark-mode secondary text.
- **Amber Accent** (`#d79628` / oklch(72% 0.14 75)): Dark-mode primary accent.
- **Amber Accent Hover** (`#eba941` / oklch(78% 0.14 75)): Dark-mode hover.
- **Amber Tint** (`#3a2b16` / oklch(30% 0.04 75)): Dark-mode alert/selected backgrounds.

### Semantic
- **Pomegranate** (`#c53637` / oklch(55% 0.18 25)): Errors and danger actions.
- **Pomegranate Tint** (`#ffe7e4` / oklch(95% 0.03 25)): Error backgrounds.
- **Success** (`#c8e8cd` bg / `#005820` text): Approved or success states.
- **Warning** (`#f7e2b8` bg / `#916a00` text): Pending or warning states.

### Named Rules
**The One Stamp Rule.** The accent color is used on ≤10% of any screen. Its rarity is what makes it feel like a mark of trust rather than a theme wash.

**The No-Cream Rule.** The light background is a green-tinted off-white (`#f6faf6`), not a warm cream or parchment. Warmth in this brand comes from the serif headings and the community voice, not from a default beige page.

## 3. Typography

**Display Font:** `Amiri`, Georgia, serif  
**Body Font:** `Noto Sans Arabic`, system-ui, sans-serif  
**Label Font:** `Noto Sans Arabic`, system-ui, sans-serif  

**Character:** A classical Arabic serif for headings paired with a neutral, modern sans for everything else. The contrast is between tradition (the book) and utility (the catalog).

### Hierarchy
- **Display** (700, `clamp(2.25rem, 6vw, 4rem)`, line-height 1.15, letter-spacing -0.02em): Hero headlines and page titles. Always `Amiri`. `text-wrap: balance`.
- **Headline** (700, `1.5rem`, line-height 1.2): Section headings (`Categories`, `Featured Editions`, `Comments`). `Amiri`.
- **Title** (700, `1.25rem`, line-height 1.3): Card titles and book names in lists. `Amiri` for edition/book titles; sans for UI labels.
- **Body** (400, `1rem`, line-height 1.7): Paragraphs, comments, descriptions. Max line length ~65–75ch. `text-wrap: pretty`.
- **Label** (500, `0.875rem`, line-height 1.4): Navigation, buttons, metadata, stat labels, form labels, badges.

### Named Rules
**The Arabic First Rule.** Headings are sized and spaced for Arabic text: generous line-height, no ultra-tight tracking, and `text-wrap: balance` to keep lines even.

## 4. Elevation

Depth is conveyed through stacked paper: surfaces rest on the page, then cards and suggestion menus rise slightly with a diffuse shadow. There are no heavy lifts, no floating glass panels, and no dramatic hover elevations. Shadows are structural, not decorative.

### Shadow Vocabulary
- **Card Shadow** (`box-shadow: 0 10px 30px oklch(0% 0 0 / 0.06)`): Cards, edition grids, search suggestions, and any surface that needs to separate from the page.
- **Card Shadow Dark** (`box-shadow: 0 10px 30px oklch(0% 0 0 / 0.25)`): The same shadow in dark mode, stronger because the background is much darker.

### Named Rules
**The Stacked Paper Rule.** Cards sit one sheet above the page at rest. They do not lift on hover; hover is signaled by border-color or background-color change, not by shadow growth.

## 5. Components

Components are refined utility: consistent 6px rounding, clear borders, and color reserved for action or state. Every interactive element has a visible focus state.

### Buttons
- **Shape:** Rounded corners (6px / `{rounded.md}`), inline-flex with centered icon + label gap.
- **Primary:** Olive Trust background (`{colors.accent}`), white text, no border. Padding `0.625rem 1.25rem`. Hover shifts to Olive Trust Hover.
- **Secondary:** Transparent background, ink text, 1px Ledger Line border. Hover fills with Olive Trust Tint and shifts border to accent.
- **Danger:** Pomegranate background, white text. Hover darkens with `filter: brightness(0.92)`.
- **Ghost:** Transparent background and border, muted text. Hover shows ink text on a surface background.
- **Link:** Transparent, accent text, no padding, underline on hover.
- **States:** `disabled` / `aria-disabled="true"` reduces opacity to 0.6 and changes cursor. Focus uses the browser default plus the component's own contrast.

### Inputs / Fields
- **Style:** Full width, 1px Ledger Line border, 6px radius, surface background, inherited font. Padding `0.625rem`.
- **Focus:** 2px outline in Olive Trust, 1px offset (`outline: 2px solid var(--accent); outline-offset: 1px`).
- **Placeholder:** Ash Ink (`{colors.muted}`).
- **Error:** Pomegranate text below the field.
- **Textarea:** Resizable vertically, minimum height 6rem.

### Cards / Containers
- **Corner Style:** 4px radius (`{rounded.sm}`).
- **Background:** Rag White (`{colors.surface}`).
- **Border:** 1px Ledger Line.
- **Shadow:** Card Shadow.
- **Internal Padding:** `1.5rem` for generic cards; `1.75rem` for edition cards.
- **Footer:** Top border in Ledger Line, flex between content and actions.

### Badges
- **Default:** Olive Trust Tint background, Olive Trust text, pill shape (`{rounded.full}`).
- **Expert:** Olive Trust background, white text, square corners (`border-radius: 0`). The expert badge is intentionally more severe because authority should not look playful.
- **Success / Warning / Danger:** Semantic background/text pairs, pill shape.

### Alerts / Messages
- **Info:** Olive Trust Tint background, ink text, 1px Ledger Line border.
- **Success / Warning / Error:** Semantic background/text pairs with matching border color.
- **Shape:** 6px radius, padding `0.75rem 1rem`.

### Navigation
- **Header:** Surface background, 1px bottom border, flex between brand and nav links.
- **Brand:** `Amiri` at `1.25rem`, bold, ink color.
- **Links:** Label size, muted color, no underline. Hover shifts to ink.
- **Theme Toggle:** 32px circular button with 1px border, transparent background, ink icon.
- **Mobile:** Nav links keep their horizontal layout but gap shrinks; user email hides below 640px.

### Like Button
- **Style:** Inline-flex, gap 0.5rem, surface background, 1px border, 6px radius, muted text.
- **Hover:** Border and text shift to Olive Trust.
- **Liked:** Olive Trust text and border, Olive Trust Tint background, filled heart icon.

## 6. Do's and Don'ts

### Do:
- **Do** use `Amiri` for every heading and `Noto Sans Arabic` for body/UI text.
- **Do** cap body measure at ~78ch (`width: min(100% - 2rem, 78ch)` is the current container).
- **Do** reserve Olive Trust/Amber Accent for primary actions, active states, expert badges, and status kicker.
- **Do** use 150ms ease transitions on color, border-color, and background-color.
- **Do** respect `prefers-reduced-motion: reduce` by disabling transitions and animations.
- **Do** keep cards flat at rest and lift them only through the static Card Shadow.
- **Do** use semantic badge colors for pending/approved/rejected/expert states.
- **Do** maintain 4px card radius and 6px button/input radius consistently.

### Don't:
- **Don't** use cream, sand, beige, or parchment as the page background. The background is Pressed Paper (`#f6faf6`), a green-tinted near-white.
- **Don't** add decorative Islamic borders, arabesque flourishes, gold gradients, or ornate frames.
- **Don't** use Bootstrap / Material default styling or generic SaaS dashboard cards.
- **Don't** create cluttered forum-style interfaces with competing borders and badges.
- **Don't** use gradient text (`background-clip: text`) for headings or labels.
- **Don't** use glassmorphism or decorative blur.
- **Don't** use side-stripe borders (colored `border-left` or `border-right` > 1px) on cards, list items, or alerts.
- **Don't** place tiny uppercase tracked eyebrows above every section.
- **Don't** use numbered section markers (`01 / 02 / 03`) as default scaffolding.
- **Don't** animate layout properties (width, height, margin) for state changes.
- **Don't** use arbitrary z-index values like 999 or 9999; build a semantic scale if needed.
