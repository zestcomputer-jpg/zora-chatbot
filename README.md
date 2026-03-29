# ZORA Ai Agent - Facebook Messenger Chatbot

A Facebook Messenger chatbot for ZEST Mobile Shop that handles phone inquiries, store info, orders, and YouTube video recommendations in Burmese.

## Features

1. **Phone Catalog Search**: Users can search for phone models (e.g., "iPhone 16", "Redmi Note 15") and get prices, specs, and stock status.
2. **YouTube Video Recommendations**: When users ask for reviews or unboxing videos, the bot recommends relevant videos from the ZEST YouTube channel.
3. **Store Information**: Provides store location, opening hours, and contact details.
4. **Order System**: A step-by-step flow to collect customer name, phone, address, and desired phone model.
5. **Burmese Language Support**: The bot is designed to understand and respond primarily in Burmese.

## Project Structure

```
zora-chatbot/
├── app.py                  # Main Flask application and webhook handler
├── update_catalog.py       # Script to fetch latest phone data from website API
├── requirements.txt        # Python dependencies
├── Procfile                # For Heroku/Render deployment
├── Dockerfile              # For Docker deployment
├── docker-compose.yml      # For Docker Compose deployment
├── .env.example            # Example environment variables
└── data/
    ├── phone_catalog.json  # Scraped phone data
    └── youtube_videos.json # Scraped YouTube videos
```

## Setup Instructions

### 1. Facebook Developer Setup

1. Go to [Facebook Developers](https://developers.facebook.com/) and create a new App (Type: Business).
2. Add the **Messenger** product to your app.
3. In the Messenger settings, link your **ZEST Mobile Shop** Facebook Page.
4. Generate a **Page Access Token** and save it.
5. You will need to set up the Webhook later (after deploying the app).

### 2. Deployment

You can deploy this application easily on platforms like Render, Heroku, or your own server.

#### Option A: Render / Heroku (Easiest)
1. Push this code to a GitHub repository.
2. Create a new Web Service on Render (or App on Heroku) connected to your repository.
3. Set the Environment Variables (see below).
4. Deploy! The platform will automatically use the `Procfile` or `Dockerfile`.

#### Option B: Docker (VPS / Server)
```bash
# Clone or copy the code to your server
cd zora-chatbot

# Copy env file and edit with your tokens
cp .env.example .env
nano .env

# Start the container
docker-compose up -d
```

### 3. Environment Variables

Set these variables in your deployment environment (or `.env` file):

- `PAGE_ACCESS_TOKEN`: The token generated from Facebook Developer Portal.
- `VERIFY_TOKEN`: A secret string you choose (e.g., `zora_verify_token_2024`). You'll need this for the webhook setup.
- `OPENAI_API_KEY`: (Optional) For AI fallback responses if the user asks complex questions.
- `PORT`: Default is 5000.

### 4. Connect the Webhook

1. Once your app is deployed, go back to the Facebook Developer Portal > Messenger > Settings.
2. Under **Webhooks**, click "Add Callback URL".
3. Callback URL: `https://your-app-url.com/webhook`
4. Verify Token: The `VERIFY_TOKEN` you set in your environment variables.
5. Click "Verify and Save".
6. Add subscriptions for: `messages`, `messaging_postbacks`.

### 5. Initialize the Bot Profile

After deployment and setting the `PAGE_ACCESS_TOKEN`, you need to initialize the bot's greeting text, "Get Started" button, and persistent menu.

Run this command once:
```bash
curl -X POST https://your-app-url.com/setup
```

## Updating Data

### Phone Catalog
To update the phone prices and stock status from the website, run the update script. This will fetch the latest data from the `zestmobileshop.com` API.

```bash
python update_catalog.py
```
*(If using Docker, run this inside the container or set up a cron job).*

## Testing Locally

You can test the bot's logic without connecting to Facebook:

```bash
# Start the server
python app.py

# Test search
curl -X POST -H "Content-Type: application/json" -d '{"q": "iPhone 16"}' http://localhost:5000/test

# Test order flow
curl -X POST -H "Content-Type: application/json" -d '{"q": "မှာမယ်", "sender": "user1"}' http://localhost:5000/test
```
