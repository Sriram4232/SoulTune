# SoulTune

AI Music Playlist Curator from Mood Description

SoulTune is a personalized music recommendation application that transforms natural-language mood descriptions into curated playlists. Users can describe how they feel, refine recommendations, save playlists, and enjoy a smooth listening experience powered by AI-assisted music curation.

Built for the modern music listener, SoulTune blends mood analysis, user preferences, playlist history, and local fallback playback into a single cohesive experience.

Repository: https://github.com/Sriram4232/SoulTune

---

## Overview

SoulTune helps users discover music that matches their current emotional state, activity, and personal taste. Instead of browsing endlessly, the app turns a simple prompt such as:

- "I need a calm, focus-friendly mix"
- "Something upbeat for a late-night drive"
- "A mellow playlist with warm indie vibes"

into a relevant, curated queue of tracks.

The application combines:
- a React-based frontend for a rich user experience
- a FastAPI backend for recommendation logic and user management
- persistent storage for user state and playlists
- local audio fallback support when previews or external metadata are unavailable

---

## Key Features

- Mood-based playlist generation from freeform text prompts
- Personalized recommendation scoring based on user preferences
- Evidence-based explanations for why each song was selected
- Playlist creation, saving, and management
- Queue generation and mood-based refinements
- Local library fallback support for playback continuity
- Authenticated user accounts and preference management
- Responsive UI with fluid motion and interactive visual effects
- Export and history features for user-created collections

---

## Tech Stack

| Layer | Technologies |
| --- | --- |
| Frontend | React, Vite, JavaScript, Tailwind CSS |
| State & Data Fetching | React Query |
| Backend | Python, FastAPI, Pydantic |
| Persistence | SQLite / MongoDB-ready architecture |
| Testing | Pytest |
| Audio | Local media scanning and fallback playback |
| Deployment | Docker-ready project structure |

---

## Conceptual Architecture

SoulTune is structured as a layered application with a clear separation between interface, business logic, and data services.

```text
┌──────────────────────────────┐
│      Presentation Layer      │
│   React + Vite Frontend      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│      Application Layer       │
│  User flows / UI state / API │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│        Domain Layer          │
│  Preferences / mood logic /  │
│  playlist ranking / curation  │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│   Infrastructure Layer       │
│ DB / media / auth / APIs     │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│    Delivery / Experience     │
│    playlists, playback, UI   │
└──────────────────────────────┘
```

This architecture keeps the frontend lightweight while enabling complex recommendation and user-state logic in the backend.

---

## Project Structure

```text
SoulTune/
├── Backend/
│   ├── app/
│   ├── data/
│   ├── tests/
│   ├── requirements.txt
│   └── ...
├── Frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── ...
├── docs/
│   └── ARCHITECTURE.md
├── fallback_songs/
├── Dockerfile
├── pytest.ini
├── start.ps1
├── .gitignore
├── .dockerignore
├── README.md
└── ...
```

---

## Prerequisites

Before running the project locally, make sure you have:

- Node.js 18+
- npm
- Python 3.10+
- pip
- Optional: MongoDB if you want to use a non-default persistence setup
- Optional: local music files under `fallback_songs` or a configured media directory

---

## Installation & Setup

### 1) Clone the repository

```bash
git clone https://github.com/Sriram4232/SoulTune.git
cd SoulTune
```

---

### 2) Install frontend dependencies

```bash
cd Frontend
npm install
```

---

### 3) Install backend dependencies

```bash
cd ../Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Running the Application

### Start the backend

```bash
cd Backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The backend is expected to run on:

```text
http://127.0.0.1:8000
```

---

### Start the frontend

```bash
cd Frontend
npm run dev
```

The frontend runs on:

```text
http://127.0.0.1:5173
```

The Vite configuration includes proxying for `/api` requests to the backend service.

---

## Environment Configuration

Depending on your environment, you may need to configure variables for:

- application secret / session settings
- database connection details
- external media / metadata providers
- local music directory paths
- authentication and OTP-related settings

A typical local setup may include:

```env
APP_ENV=development
DATABASE_URL=sqlite:///./soultune.db
LOCAL_MUSIC_PATH=./fallback_songs
SECRET_KEY=your-secret-key
```

If you are using external integrations or a non-default persistence setup, add the corresponding values before starting the backend.

---

## Core User Flow

1. User signs in and configures preferences.
2. User enters a mood or activity description.
3. The backend interprets the prompt and ranks tracks against user preferences.
4. Matching songs are assembled into a playlist or active queue.
5. Explanations are generated for the strongest recommendations.
6. User can refine, save, export, or continue the generated mix.

---

## Local Audio & Fallback Behavior

SoulTune supports local audio fallback to ensure that recommendations still work when external playback or metadata is unavailable. The repo includes a `fallback_songs` directory, which is used as a local library source for playback continuity.

This provides:
- resilience when previews are unavailable
- local offline playback support
- safer user experience under external service outages

---

## Documentation

Architecture and project design notes are available here:

- `docs/ARCHITECTURE.md`

This file explains the curation flow, persistence strategy, metadata handling, and design decisions behind the recommendation engine.

---

## Testing

The repository includes Pytest-based testing under the backend:

```bash
cd Backend
source .venv/bin/activate
pytest
```

This is useful for validating app behavior and backend logic as the project evolves.

---

## Development Notes

The project is organized to be easy to extend:

- Frontend logic and UI live in `Frontend/src`
- Backend application logic lives under `Backend/app`
- Local media fallback assets live in `fallback_songs`
- Architecture documentation is stored in `docs/`

---

## Contributing

Contributions are welcome. If you want to improve the project:

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Validate locally
5. Open a pull request with a clear summary

---

## Project Status

SoulTune is an active music recommendation and curation application focused on making personalized listening more intuitive and emotionally aligned with the user’s current mood.

---

## Contact

Project repository:
- https://github.com/Sriram4232/SoulTune

---

## Summary

SoulTune is a mood-driven music discovery platform that combines AI-assisted recommendation logic with a polished and interactive frontend. It aims to transform simple emotional prompts into meaningful, personalized playlists that reflect user intent, preferences, and listening context.
