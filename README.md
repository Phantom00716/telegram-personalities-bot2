# telegram-personalities-bot (Render ready)

Deploy steps:
1. Push this repo to GitHub.
2. Create a new Web Service on Render, connect your GitHub repo.
3. Render will build using Dockerfile. After deployment, set environment variables in Render:
   - TELEGRAM_TOKEN (your Telegram bot token)
   - OPENAI_API_KEY (your OpenAI API key)
   - ADMIN_IDS (optional, e.g. 761662415)
   - DATABASE_PATH (optional, default data.db)
4. After the service is live, set BASE_URL env var to https://<your-service>.onrender.com and restart.
5. Open https://<your-service>.onrender.com/set_webhook to register webhook with Telegram.
