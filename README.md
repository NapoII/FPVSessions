# FPVSessions 🚀

A modern, self-hosted FPV (First-Person View) session browser and sharing app. Browse your recorded sessions, preview videos and images, manage tags, generate share links, and download original files—all in a clean, dark UI.

> Fast to set up, easy to use, and production-ready with Gunicorn + Nginx.

---

## Table of Contents

- [Features](#features-)
- [Quickstart (Local)](#quickstart-local-)
- [Project Structure](#project-structure-)
- [Auto organize & rename](#auto-organize--rename-)
- [Deployment (VPS)](#deployment-vps-)
- [Tech Stack](#tech-stack-)
- [License](#license)

---

## Features ✨

- Session overview with stats (videos, images, size, duration)
- Inline video player and image grid with lightbox
- Share links for single videos (public share page with embed meta tags)
- Download buttons for videos, logs, blackbox files, and metadata
- Tags: add/remove and save per session
- Admin Settings page: rebuild sessions index, manage users and permissions, upload drone images, set FPV base folder
- Consistent dark UI with Bootstrap 5 + Font Awesome icons
- Tames your FPV file jungle: scans your raw camera/goggle/blackbox dumps, auto-sorts them into clean session folders, and can optionally rename files to a consistent pattern
- Automatic thumbnails for videos and images; handy session cover art
- Powerful search and filter by date, tags, and filename
- Works even without the web UI: the organizer scripts build the tidy folder structure that the app can browse later

---

## Quickstart (Local) 🧪

1) Create and activate a virtual environment

```bash
python -m venv .venv
# Windows (PowerShell)
. .venv\\Scripts\\Activate.ps1
# Linux/macOS
# source .venv/bin/activate
```

2) Install dependencies

```bash
pip install -r FPVSession/requirements.txt
```

3) Run the app (development)

```bash
python FPVSession/wsgi.py
```

Open http://localhost:8007

> For production, use Gunicorn and (optionally) Nginx. See the Deployment section below.

---

## Project Structure 📁

```
My_FPV/
├─ FPVSession/
│  ├─ flask_app/
│  │  ├─ app.py, templates/, static/, utils/
│  │  └─ sessions_config.json, users.json
│  ├─ wsgi.py
│  └─ requirements.txt
└─ how-to-deploy/
   ├─ deploy.readme.en.md
   ├─ gunicorn.my_fpv.service
   └─ nginx.conf
```

---

## Auto organize & rename 🗂️

Beat the FPV media chaos. FPVSessions can scan your source folders and:

- Group files by session (date/time range),
- Create a clean, consistent folder layout (e.g., FPV_Camera, Goggles, Blackbox, IMG, Meta),
- Optionally rename files to a canonical, sortable pattern,
- Generate thumbnails for quick browsing.

Where: see `auto_session_sorter/` for helper scripts like `1._Auto_rename.py` and `2._Auto_session.py`.

Use the organizer to prepare your library even if you don’t run the web UI yet—the app will happily index and browse the structure later.

---

## Deployment (VPS) 🌐

A complete step-by-step guide (system user, venv, systemd service, and Nginx reverse proxy):

- 👉 [how-to-deploy/deploy.readme.en.md](how-to-deploy/deploy.readme.en.md)

You can also find example service and Nginx configs here:

- `how-to-deploy/gunicorn.my_fpv.service`
- `how-to-deploy/nginx.conf`

---

## Tech Stack 🧰

- Backend: Flask
- Frontend: Bootstrap 5, Font Awesome
- Server: Gunicorn (WSGI), optional Nginx reverse proxy

---

## License ⚖️

This project is provided as-is. Add your chosen license here (e.g., MIT, Apache-2.0).
