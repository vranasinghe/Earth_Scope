# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: university and school students and their educators learning how environmental change is measured. They use Earth Scope in coursework, labs and lectures to pick a place or area, retrieve real NASA POWER data, and judge whether a trend is statistically meaningful. Secondary: technically curious visitors and analysts who want the numbers and the provenance.

## Product Purpose
Earth Scope turns real NASA POWER monthly data into honest, explained trend analysis for any point, rectangle, country or custom polygon on Earth. Success is a user who can say what changed, how confident the statistics are, and where the data came from, without overstating the result.

## Positioning
A teaching-grade scientific instrument rather than a climate dashboard: every number is traceable to a NASA request, trends are tested with several methods (OLS, Mann-Kendall and autocorrelation-aware variants, Sen's slope, HAC), spatial maps are corrected for multiple testing over the complete cell family, and large countries run as durable background jobs whose results equal the synchronous ones.

## Operating Context
Used on laptops in classrooms and at home, sometimes projected in lectures, sometimes on phones. Workflows: Point Analysis (explore), Regional Analysis (rectangle / country / polygon, spatial trend explorer), Compare (2–3 locations), Analysis Jobs (background processing), Learn (concepts), result dashboards with exports.

## Capabilities and Constraints
- Only real NASA POWER data is shown; there is no synthetic or demo data.
- Provenance (source, parameter, units, boundary version, request manifest), scientific caveats must stay available; they may be condensed or moved, not removed.
- Existing routes and workflows are preserved: `/`, `/explore`, `/results`, `/compare`, `/regional`, `/regional/results`, `/jobs`, `/jobs/:id`, `/learn`.
- Stack: React 19 + TypeScript + Vite + Tailwind CSS 4, Leaflet maps, Recharts charts; no new large dependencies.

## Brand Commitments
- Name: Earth Scope. Existing logo mark in `src/components/layout/Logo.tsx`.
- Cyan/teal accent identity is kept (user-confirmed: refine the current identity, do not replace it).
- Theme: light and dark, defaulting to the visitor's system setting, with a Light / Dark / System switch in the header (user-confirmed).
- Independent educational project; not affiliated with or endorsed by NASA.

## Evidence on Hand
Real outputs from live NASA POWER validations (Sri Lanka, Brazil, Australia, United States, Canada, Russia) documented in the repository README. No testimonials, user counts or institutional endorsements exist; none may be invented.

## Product Principles
1. Honest before impressive: never overstate significance, coverage or causation.
2. Provenance is part of the answer, shown compactly and always reachable.
3. Teach through the workflow: essentials first, explanations one click away.
4. Real data by default; synthetic data is loud about itself.
5. One clear next action per screen.

## Accessibility & Inclusion
Used by students in classrooms and on projectors: readable type at distance, WCAG AA contrast in both themes, full keyboard operation, visible focus, colour never the only carrier of meaning (significance maps also use outlines/patterns).
