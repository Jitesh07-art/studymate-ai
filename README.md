# StudyMate AI

StudyMate AI is a local, single-user study assistant built with Flask, SQLite, HTML, CSS, and vanilla JavaScript. It can summarize notes, make multiple-choice quizzes, score quiz attempts on the server, and create persistent flashcard decks. The dashboard and history pages use saved data from your local SQLite database.

## Project structure

```text
.
├── app.py                 # Flask pages and JSON APIs
├── ai_service.py          # Provider calls, prompts, demo examples, validation
├── config.py              # Environment-based configuration
├── database.py            # SQLite schema and data helpers
├── requirements.txt
├── .env.example           # Safe configuration template
├── instance/
│   └── studymate.db       # Created on first run (ignored by Git)
├── templates/             # Flask-rendered HTML pages
├── static/
│   ├── css/style.css
│   └── js/app.js           # Accessible page interactions and API requests
└── tests/test_app.py
```

## Run on Windows

Open this folder in Visual Studio Code, then open **Terminal → New Terminal** and run:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

If PowerShell blocks activation, use `venv\Scripts\python.exe -m pip install -r requirements.txt` and then `venv\Scripts\python.exe app.py`. Visit **http://127.0.0.1:5000**. Stop the server with Ctrl+C. The database is created automatically in `instance/studymate.db` and remains after restarting the server.

## Configure genuine AI

1. Create an API key in your chosen provider's developer dashboard.
2. Open the local `.env` file and set `AI_API_KEY` to the key. Keep `.env` private; it is excluded by `.gitignore` and is never returned by an API endpoint.
3. Set `AI_PROVIDER` and `AI_MODEL` to the provider label and model available to your account. The included integration uses the official OpenAI Python SDK and OpenAI-compatible chat completions. For a compatible provider, set its documented `AI_BASE_URL` too.
4. Leave `AI_DEMO_MODE=false` for genuine provider-backed results. Restart Flask after changing `.env`.

The current AI integration expects an OpenAI-compatible chat completions endpoint. Provider errors are returned as readable setup/request messages without echoing credentials or provider response details.

## Try without an API key

Set `AI_DEMO_MODE=true` in `.env`, then restart the app. The app will generate clearly identified sample outputs from the notes you enter. Demo examples are not presented as genuine AI responses. Set it back to `false` when configuring a real key. With demo mode off and no key, the UI displays a clear setup error when an AI feature is requested.

## Test

With the virtual environment active, run:

```powershell
python -m unittest discover -s tests -v
```

The tests use temporary databases and cover page/health responses, empty input validation, summary persistence, answer-key privacy and scoring, flashcard persistence/deletion, and the missing-key setup message.

## Deploy on Render

The included [render.yaml](./render.yaml) describes a free Render web service. To deploy:

1. Publish this project to a GitHub repository. Keep `.env` out of GitHub; `.gitignore` excludes it.
2. In Render, choose **New → Blueprint**, connect the repository, and apply the `render.yaml` configuration.
3. If you want genuine AI-generated study materials, add `AI_API_KEY` in the Render service's **Environment** settings. Use a key supported by the configured OpenAI-compatible provider, and never commit it to GitHub. To use sample outputs without a key, change `AI_DEMO_MODE` to `true` in the service settings.
4. After deployment, open the service URL and check `/api/health`. A healthy response reports `"status": "ok"` and `"database": "connected"`.

This configuration uses Render's free instance and the app's local SQLite database. The database is temporary on this service: saved summaries, quizzes, flashcards, and settings can be lost when the service restarts or is redeployed, and the service may spin down while idle. Persistent disks require a paid service; see Render's [disk documentation](https://render.com/docs/disks) and [free service limitations](https://render.com/docs/free) before changing plans.

The app does not have user sign-in. Anyone who can reach the deployed URL can use it, so do not enter sensitive or private study material.

## Architecture and data

Flask serves six template pages and JSON endpoints. Browser JavaScript sends study material to Flask; only `ai_service.py` talks to the configured AI provider. SQLite uses four main content tables: `summaries` stores source notes and saved summary text; `quiz_sessions` stores the generated questions and private answer keys; `quiz_attempts` stores submitted answers and scores; and `flashcard_sets` stores generated card decks. A small `settings` table keeps theme and language preferences. Quiz generation returns questions without answer indexes, and `/api/quiz/submit` calculates and saves the score on the server.

## Feature checklist

- [x] Responsive dashboard with real saved-data counts and recent activity
- [x] Summary generation, copy, and SQLite save
- [x] Quiz generation, navigation, server-side scoring, explanations, and saved attempts
- [x] Flashcard generation, flip, shuffle, practice markers, saved decks, and reopening
- [x] Searchable/filterable history with viewing and confirmation before deletion
- [x] Light/dark theme and saved language preference
- [x] Backend-only API key, input limits, readable errors, and labeled demo mode
- [x] Automated Flask API tests
