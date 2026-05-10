# Render Deployment (MyHealthVibe)

## 1) Push this project to GitHub
- Create a new GitHub repository.
- Push this folder (`app.py`, `requirements.txt`, `render.yaml`) to that repo.

## 2) Create Render service
- In Render, click **New +** -> **Blueprint**.
- Connect your GitHub repo.
- Render will detect `render.yaml` and create:
  - Web service (`myhealthvibe-dashboard`)
  - Persistent disk (`/var/data`)

## 3) Deploy
- Click **Apply** / **Create Resources**.
- Wait for build and deploy.
- Open the generated `https://...onrender.com` URL.

## 4) Verify data persistence
- Add a few records from your phone.
- Refresh page and confirm data remains.
- Render stores DB at `/var/data/health_dashboard.db`.

## 5) Phone usage
- Open your Render URL directly in iPhone Safari.
- If you later enable webhook sender on phone, point it to:
  - `https://<your-render-domain>/webhook`
