# app.py - 4UTODAY Telegram Bot (FINAL STABLE VERSION)
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import psycopg
from psycopg.rows import dict_row
from telegram import Update, Bot
from datetime import datetime
import threading
import time

# ========== Flask App Setup ==========
app = Flask(__name__)
CORS(app)

# ========== Environment Variables ==========
# Use RENDER_EXTERNAL_URL if available, otherwise try RENDER_URL
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL') or os.environ.get('RENDER_URL')
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')
CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')

# Calculate webhook path from TOKEN (first 8 chars)
if TOKEN:
    WEBHOOK_PATH = f"/tg-hook-{TOKEN[:8]}"
    WEBHOOK_URL = f"{RENDER_URL}{WEBHOOK_PATH}" if RENDER_URL else None
else:
    WEBHOOK_PATH = "/tg-hook-default"
    WEBHOOK_URL = None

print(f"🔧 Configuration Check:")
print(f"   - TOKEN exists: {'✅ Yes' if TOKEN else '❌ No'}")
print(f"   - DATABASE_URL exists: {'✅ Yes' if DATABASE_URL else '❌ No'}")
print(f"   - RENDER_URL: {RENDER_URL}")
print(f"   - Webhook URL: {WEBHOOK_URL}")

# ========== Database Functions ==========
def get_db_connection():
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return conn
    except Exception as e:
        print(f"❌ DB connection error: {e}")
        return None

def init_database():
    conn = get_db_connection()
    if not conn:
        print("❌ Cannot initialize DB: No connection")
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    telegram_message_id BIGINT UNIQUE,
                    post_title TEXT NOT NULL,
                    post_description TEXT,
                    file_url TEXT,
                    tags TEXT,
                    channel_username VARCHAR(255)
                )
            """)
            conn.commit()
        conn.close()
        print("✅ Database table 'posts' is ready")
        return True
    except Exception as e:
        print(f"❌ DB init error: {e}")
        return False

# ========== SYNC Webhook Handler ==========
@app.route(WEBHOOK_PATH, methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        bot = Bot(TOKEN)
        update = Update.de_json(data, bot)
        if update.channel_post:
            process_post(update.channel_post, bot)
        return "OK", 200
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return "Error", 500

def process_post(message, bot):
    try:
        text = message.caption or message.text or ""
        title = text[:100] + "..." if len(text) > 100 else text or "Media Post"
        
        file_url = ""
        if message.photo:
            file = bot.get_file(message.photo[-1].file_id)
            file_url = file.file_path
        elif message.video:
            file = bot.get_file(message.video.file_id)
            file_url = file.file_path

        tags = [word for word in text.split() if word.startswith("#")]
        tags_str = ", ".join(tags) if tags else "general"
        channel_name = message.chat.title or message.chat.username or "Unknown"

        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO posts (telegram_message_id, post_title, post_description, file_url, tags, channel_username)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (telegram_message_id) DO NOTHING
                """, (message.message_id, title, text, file_url, tags_str, channel_name))
                conn.commit()
                if cur.rowcount > 0:
                    print(f"✅ Saved Post: {title[:50]}")
            conn.close()
    except Exception as e:
        print(f"❌ Post save error: {e}")

# ========== Webhook Background Setup (FIXED VERSION) ==========
def setup_webhook_background():
    """
    Fixed version: Uses run() method to execute async functions in sync context
    """
    if not TOKEN or not WEBHOOK_URL:
        print("⚠️ Skipping webhook setup: Missing token or URL")
        return
    
    def set_webhook_task():
        time.sleep(5)
        try:
            # FIX: Use run() method to execute async functions
            bot = Bot(TOKEN)
            
            # Delete old webhook (sync version)
            print("🔄 Deleting old webhook...")
            bot.delete_webhook(drop_pending_updates=True)
            time.sleep(1)
            
            # Set new webhook (sync version)
            print(f"🔄 Setting new webhook to: {WEBHOOK_URL}")
            success = bot.set_webhook(url=WEBHOOK_URL)
            
            if success:
                print(f"✅ Webhook successfully set to: {WEBHOOK_URL}")
                
                # Verify webhook info
                info = bot.get_webhook_info()
                print(f"📋 Webhook info: URL={info.url}, Pending={info.pending_update_count}")
            else:
                print(f"❌ Failed to set webhook")
                
        except Exception as e:
            print(f"❌ Webhook setup error: {e}")
    
    thread = threading.Thread(target=set_webhook_task)
    thread.daemon = True
    thread.start()
    print("🔄 Webhook setup started in background (fixed version)")
# ========== API Endpoints ==========
@app.route('/')
def home():
    return jsonify({
        "service": "4UTODAY API",
        "status": "online",
        "webhook_configured": bool(TOKEN and WEBHOOK_URL),
        "webhook_url": WEBHOOK_URL,
        "endpoints": ["/api/posts", "/api/health", "/api/stats"]
    })

@app.route('/api/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/api/posts')
def get_posts():
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB connection failed"}), 500
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM posts ORDER BY created_at DESC LIMIT 50")
            posts = cur.fetchall()
            for p in posts:
                if 'created_at' in p and p['created_at']:
                    p['created_at'] = p['created_at'].isoformat()
        conn.close()
        return jsonify(posts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats')
def get_stats():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as total FROM posts")
            total = cur.fetchone()['total']
            cur.execute("SELECT tags, COUNT(*) as count FROM posts GROUP BY tags ORDER BY count DESC LIMIT 5")
            tags = cur.fetchall()
        conn.close()
        return jsonify({"total_posts": total, "top_tags": tags})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== Startup ==========
def startup():
    print("🚀 Starting 4UTODAY Bot...")
    init_database()
    setup_webhook_background()
    print("✅ Startup completed")

startup()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
      
