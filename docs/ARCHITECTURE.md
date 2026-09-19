# Implementation architecture

The browser talks to FastAPI on `/api/v1`. During development Vite proxies the API; the production build is served by FastAPI on the same origin. React holds UI state and the session-bound CSRF token in memory. TanStack Query handles reusable server data. Mood drafts remain in memory and are cleared when accounts change; no prompt is stored in browser storage.

## Curation flow

1. Load the authenticated user's preferences and the previous structured profile for refinements.
2. Parse the new description locally. If Groq is configured, validate its JSON interpretation, preserving explicit constraints. On failure, use the deterministic interpretation and disclose the fallback.
3. Scan the local library and retrieve/cache optional Last.fm metadata. Use fictional demo metadata only for an empty, unconfigured installation. Real queues are never padded with demo songs.
4. Apply hard exclusions before ranking: genre, artist, explicit-content rating, language, instrumental-only, specified tempo ranges, decade, and avoided moods.
5. Calculate a weighted match: mood 30%, energy 20%, valence 15%, genre 10%, tempo 10%, activity 10%, popularity 5%. Unknown numeric features are disclosed as neutral estimates, not fabricated measurements.
6. Remove duplicate/remastered variants, limit artist repetition, balance genres, and rank the selected tracks by match score; the activity's energy progression breaks equal-score ties.
7. Generate short explanations directly from scoring evidence. Replace the account’s single active mood queue, or refine it in place. Persist its original request, updated profile, version and conversation. Named collections are created only by explicit user action, with independently saved songs stored separately. An LLM never invents the displayed score.

External providers have bounded timeouts. Last.fm metadata caching is process-local and expires; durable user state is stored independently. A provider outage does not invalidate local playback or previously saved history.

## Persistence and authorization

The storage adapter supports SQLite locally and MongoDB when configured. Users, OTP challenges, hashed opaque sessions, queues/collections, saved songs, deletion markers, and rate-limit counters use separate kinds/collections. User email uniqueness is enforced by storage. Every playlist read or mutation is scoped to its owner; missing and unauthorized resources both return 404.

An account session is issued only after password and browser-bound email OTP verification. OTP hashes use HMAC with a server secret; atomic consume operations count attempts and prevent replay. Login is unavailable if email delivery is unconfigured. Guest accounts are isolated and expire. Signing out removes guest data, while registered accounts retain history. Passwords use scrypt with per-password random salts. Cookie identifiers are hashed before persistence. CSRF tokens bind mutations to the authenticated session. Production requires HTTPS cookies and explicit origins.

## Local audio

`music.py` scans only `fallback_songs` (or the configured directory). It rejects symlinks/junctions and only resolves opaque IDs for supported audio extensions. Embedded tags, user folder labels and optional sidecar JSON supply metadata. Folder labels only add mood tags, not fabricated numeric measurements. FastAPI serves the verified file with HTTP range support; the frontend uses a real audio element for transport, seeking and volume.

Metadata-only demo recommendations never acquire fake playback URLs. The player switches to actual local tracks when a preview is unavailable, reports the switch, and handles an empty or unreadable library without claiming that sound is playing.

## Scope

All must-have problem-statement flows are implemented: natural-language mood input, recommendations, evidence-based explanations, conversational refinements retaining context, exports, and history. Analytics, preferences, secure authentication and local playback extend those flows. Spotify-specific OAuth/export and collaboration remain optional future integrations. See the README for deployment and configuration.
