# JLA - Job Listing app

Two projects, one system:

- **[job-search-automation](./job-search-automation)** — fetches, filters and
  scores remote job listings with a local LLM, persists them to Postgres,
  and exposes them (plus its own config) over an HTTP API.
- **[job-listings-app](./job-listings-app)** — a Nuxt UI that reads those
  listings and lets you browse/filter them, and edit the backend's
  `config.yaml` from a `/settings` page.

```
jla/
├── docker-compose.yml
├── job-search-automation/   # backend: scraping, scoring, Postgres, API
└── job-listings-app/        # frontend: Nuxt UI
```

## Run everything

```bash
cd job-search-automation && cp config.yaml.example config.yaml && cd ..
cd job-listings-app && cp .env.example .env && cd ..

docker compose up -d --build
```

- Frontend: http://localhost:3000/jobs
- Settings panel: http://localhost:3000/settings
- Backend API: http://localhost:8000 (docs at `/docs`)

Populate the database with a scan:

```bash
docker compose run --rm backend python main.py
```

Ollama isn't part of this compose file — point `OLLAMA_URL` (in
`docker-compose.yml`, or `ollama.url` in `config.yaml`/the settings panel)
at wherever it actually runs: your host, or another container on your
shared Docker network.

## How the pieces talk to each other

```
job-listings-app (Nuxt)
  server/api/jobs.ts       --> GET  backend:8000/jobs
  server/api/settings.get.ts --> GET  backend:8000/config
  server/api/settings.put.ts --> PUT  backend:8000/config

job-search-automation (FastAPI)
  GET  /jobs     --> reads Postgres
  GET  /config   --> reads config.yaml
  PUT  /config   --> validates + writes config.yaml
  POST /run      --> runs the scan pipeline in the background
```

The browser never talks to the backend directly — Nuxt's server routes
proxy it, so `NUXT_BACKEND_URL` is the only place that knows the backend's
address.

## Scheduling scans

`POST /run` triggers a scan on demand, but nothing calls it periodically.
Wire that up however fits your setup — a host cron job running
`docker compose run --rm backend python main.py`, a systemd timer, or a
call to `POST http://localhost:8000/run` from whatever scheduler already
runs on your shared Docker network.

See each project's own README for details specific to that half of the
system.
