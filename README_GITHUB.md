# ZORA Ai Agent - Facebook Messenger Chatbot for ZEST Mobile Shop

A production-ready Facebook Messenger chatbot that provides real-time phone pricing, stock status, YouTube recommendations, and order management for ZEST Mobile Shop in Pyawbwe, Myanmar.

## Features

- **Real-Time Phone Catalog**: Automatically syncs with zestmobileshop.com API every 10 minutes
- **Smart Search**: Find phones by brand, model, or specifications
- **Stock Status**: Shows in-stock, out-of-stock, and pre-order availability
- **YouTube Integration**: Recommends relevant unboxing and review videos
- **Order Management**: Multi-step order flow collecting customer details
- **Burmese Language**: Full support for Burmese language queries and responses
- **Keep-Alive Mechanism**: Prevents Render free tier from sleeping (pings every 12 minutes)
- **Intelligent Caching**: 10-minute cache to balance freshness and performance

## Quick Start

### Deploy to Render (Free Tier)

1. **Fork or clone this repository** to your GitHub account
2. **Go to [Render.com](https://render.com)** and sign in with your GitHub account
3. **Create a new Web Service**:
   - Connect your GitHub repository
   - Set Build Command: `pip install -r requirements.txt`
   - Set Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. **Add Environment Variables** in Render dashboard:
   - `PAGE_ACCESS_TOKEN`: Your Facebook Page Access Token
   - `VERIFY_TOKEN`: Your webhook verify token (e.g., `zora_verify_token_2024`)
   - `RENDER`: Set to `true` (enables keep-alive mechanism)
   - `ENVIRONMENT`: Set to `production`
5. **Deploy** and get your public URL
6. **Configure Facebook Webhook**:
   - Go to Facebook Developer Portal > Your App > Messenger > Settings
   - Add Callback URL: `https://your-render-url/webhook`
   - Verify Token: Your `VERIFY_TOKEN`
   - Subscribe to: `messages`, `messaging_postbacks`

### Local Development

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/zora-chatbot.git
cd zora-chatbot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export PAGE_ACCESS_TOKEN="your_token_here"
export VERIFY_TOKEN="your_verify_token"

# Run the server
python app.py
```

## Project Structure

```
zora-chatbot/
├── app.py                      # Main Flask application with webhook handler
├── requirements.txt            # Python dependencies
├── Procfile                    # For Heroku/Render deployment
├── Dockerfile                  # For Docker deployment
├── docker-compose.yml          # Docker Compose configuration
├── .env.example                # Example environment variables
├── .gitignore                  # Git ignore rules
├── data/
│   └── youtube_videos.json     # Scraped YouTube channel videos
└── README_GITHUB.md            # This file
```

## How It Works

### Phone Catalog Sync
- **Startup**: Fetches all phones from `zestmobileshop.com/api/trpc/phones.search`
- **Caching**: Stores data for 10 minutes to improve performance
- **Auto-Refresh**: After 10 minutes, fetches fresh data automatically
- **Result**: Prices and stock status always reflect your website

### Keep-Alive (Render Free Tier)
- **Problem**: Render free tier puts apps to sleep after 15 minutes of inactivity
- **Solution**: Background thread pings `/health` endpoint every 12 minutes
- **Activation**: Automatically enabled when `RENDER=true` environment variable is set

### Message Flow
1. User sends message to Facebook Page
2. Webhook receives message event
3. Intent detection (greeting, phone search, order, etc.)
4. Fetch fresh phone data from cache
5. Generate response with current prices/stock
6. Send response via Facebook Messenger API

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Health check / API info |
| `/health` | GET | Server health status |
| `/webhook` | GET | Facebook webhook verification |
| `/webhook` | POST | Receive messages from Facebook |
| `/test` | GET/POST | Test chatbot without Facebook |
| `/setup` | POST | Initialize Messenger profile |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PAGE_ACCESS_TOKEN` | Yes | Facebook Page Access Token |
| `VERIFY_TOKEN` | Yes | Webhook verification token |
| `OPENAI_API_KEY` | No | For AI fallback responses |
| `PORT` | No | Server port (default: 5000) |
| `RENDER` | No | Set to `true` on Render to enable keep-alive |
| `ENVIRONMENT` | No | Set to `production` to enable keep-alive |
| `SERVER_URL` | No | For keep-alive pings (auto-detected on Render) |

## Testing

### Test Phone Search
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"q": "iPhone 16"}' \
  http://localhost:5000/test
```

### Test Order Flow
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"q": "မှာမယ်", "sender": "user123"}' \
  http://localhost:5000/test
```

### Test Store Info
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"q": "ဆိုင်"}' \
  http://localhost:5000/test
```

## Troubleshooting

### "No phones found" error
- Check if `zestmobileshop.com` API is accessible
- Verify cache is initialized (check logs)
- Try manual test: `curl https://zestmobileshop.com/api/trpc/phones.search?...`

### Keep-alive not working
- Ensure `RENDER=true` or `ENVIRONMENT=production` is set
- Check logs for "Keep-alive mechanism activated"
- Verify `SERVER_URL` is correct (should auto-detect on Render)

### Webhook not receiving messages
- Verify `PAGE_ACCESS_TOKEN` is correct
- Check webhook verification in Facebook Developer Portal
- Ensure page is subscribed to webhook
- Check application logs for errors

## Deployment Platforms

### Render (Recommended for Free Tier)
- Free tier with keep-alive support
- GitHub integration
- Automatic deployments
- [Deploy Guide](https://render.com/docs)

### Heroku
- Use `Procfile` for deployment
- Set environment variables in dashboard
- `heroku create` and `git push heroku main`

### Docker
```bash
docker-compose up -d
```

### Your Own VPS
```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 2 --timeout 120
```

## Store Information

**ZEST Mobile Shop**
- 📍 မဘ-၁၄၃၊လမ်းမတော်, တရားရုံးရှေ့, မြင်းဘက်ရပ်ကွက်, ပျော်ဘွယ်မြို့
- ☎ 09 797 8855 85
- ☎ 09 9649 555 99
- 🕐 8:00 AM - 7:00 PM (Daily)
- 🌐 https://zestmobileshop.com
- 💬 m.me/zestmobileshop

## Support

For issues or questions:
1. Check the logs: `heroku logs --tail` or Render dashboard
2. Test the `/test` endpoint locally
3. Verify environment variables are set
4. Check Facebook Developer Portal webhook logs

## License

This project is proprietary software for ZEST Mobile Shop.

## Author

Created by Manus AI for ZEST Mobile Shop
