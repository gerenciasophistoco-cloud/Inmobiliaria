---
name: Nocturne Estate
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#393939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1b1c1c'
  surface-container: '#1f2020'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353535'
  on-surface: '#e4e2e1'
  on-surface-variant: '#c4c7c7'
  inverse-surface: '#e4e2e1'
  inverse-on-surface: '#303030'
  outline: '#8e9192'
  outline-variant: '#444748'
  surface-tint: '#c8c6c5'
  primary: '#c8c6c5'
  on-primary: '#313030'
  primary-container: '#121212'
  on-primary-container: '#7e7d7d'
  inverse-primary: '#5f5e5e'
  secondary: '#c6c6c7'
  on-secondary: '#2f3131'
  secondary-container: '#454747'
  on-secondary-container: '#b4b5b5'
  tertiary: '#e9c349'
  on-tertiary: '#3c2f00'
  tertiary-container: '#181100'
  on-tertiary-container: '#987a00'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e5e2e1'
  primary-fixed-dim: '#c8c6c5'
  on-primary-fixed: '#1c1b1b'
  on-primary-fixed-variant: '#474646'
  secondary-fixed: '#e2e2e2'
  secondary-fixed-dim: '#c6c6c7'
  on-secondary-fixed: '#1a1c1c'
  on-secondary-fixed-variant: '#454747'
  tertiary-fixed: '#ffe088'
  tertiary-fixed-dim: '#e9c349'
  on-tertiary-fixed: '#241a00'
  on-tertiary-fixed-variant: '#574500'
  background: '#131313'
  on-background: '#e4e2e1'
  surface-variant: '#353535'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '700'
    lineHeight: '1'
    letterSpacing: 0.1em
  badge-text:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '800'
    lineHeight: '1'
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  container-padding: 48px
  gutter: 24px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
---

## Brand & Style
The design system is engineered to evoke exclusivity, prestige, and modern luxury. Targeting high-net-worth individuals and discerning home buyers, it utilizes a **Glassmorphic-Minimalist** hybrid style. The aesthetic relies on the interplay between deep, obsidian-toned backgrounds and ethereal, semi-transparent layers that suggest depth without adding visual bulk. The emotional response is one of calm confidence and architectural precision. Visual interest is generated through high-contrast accents and impeccable photographic presentation rather than decorative flourishes.

## Colors
The palette is rooted in a monochromatic "Dark Charcoal" foundation to allow property photography to remain the focal point. 
- **Primary:** A rich, matte black (#121212) used for the canvas.
- **Secondary:** Pure white (#FFFFFF) reserved strictly for typography and high-frequency iconography.
- **Overlays:** Semi-transparent variations of the neutral gray (rgba(38, 38, 38, 0.6)) create the "glass" effect for content containers.
- **Accents:** A subtle metallic gold or muted slate may be used sparingly for "Sold" statuses or premium tier markers, though the default remains a high-contrast black-on-white execution.

## Typography
This design system utilizes **Inter** for its mathematical precision and exceptional readability in low-light UI environments. Headlines should use tighter letter spacing to feel "locked" and architectural. Body text requires generous line height (1.5+) to ensure legibility against dark backgrounds. Use the `label-caps` style for property metadata (e.g., "SQUARE FOOTAGE") to create a structured, editorial feel.

## Layout & Spacing
The layout follows a **Fixed Grid** model (12 columns) optimized for high-resolution print and tablet displays. A 48px safety margin is maintained around the perimeter to reinforce the "gallery" feel. Vertical rhythm is governed by an 8px base unit. Negative space is used aggressively to separate property details from the hero imagery, ensuring the layout never feels crowded or "salesy."

## Elevation & Depth
Depth is achieved through **Backdrop Blurs** and **Tonal Layering** rather than traditional drop shadows. 
1. **Base:** The primary charcoal background.
2. **Surface:** Semi-transparent glass panels (Background Blur: 20px) with a subtle 1px white border at 10% opacity.
3. **Floating:** Hero badges and neighborhood tags sit on the highest Z-index with a sharp, high-contrast fill and no transparency.
Avoid soft, fuzzy shadows; prefer crisp, defined edges for all container overlaps.

## Shapes
The shape language is refined and approachable. The standard radius is 16px (`rounded-lg`) for major image cards and content containers. Smaller components like badges and buttons utilize a 4px radius or a full pill-shape to contrast against the larger structural blocks. This mix of large soft corners and sharp internal details mimics modern architectural trends.

## Components
- **Image Cards:** Must feature a 16px corner radius. Overlays containing price or status should be anchored to the bottom-left, using the glassmorphic style.
- **Neighborhood Badges:** High-contrast, solid white background with black `badge-text`. These function as "stamps" of location authority.
- **Checkmark Bullet Points:** Minimalist, thin-stroke white checkmarks. No circular enclosure; the icon stands alone to maintain a clean vertical line.
- **Property Stat Bar:** A horizontal row of icons (Beds, Baths, Sqft) using thin-weight line icons and `label-caps` typography.
- **Call to Action:** Primary buttons are solid white with black text; secondary buttons are "ghost" style with a 1px white border.
- **Agent Footer:** Features a circular headshot crop and a blurred-glass background to separate contact info from the property details.