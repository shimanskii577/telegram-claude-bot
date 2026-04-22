import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
PORT            = int(os.getenv("PORT", 8080))

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

conversation_history: dict[int, list] = {}

SYSTEM_PROMPT = """Ти — персональний AI асистент.
Відповідай українською мовою якщо користувач пише українською.
Будь корисним, точним і лаконічним."""


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_ID:
        return True
    return str(user_id) == ALLOWED_USER_ID


# Мінімальний HTTP сервер щоб Render не вбивав процес
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # вимкнути логи HTTP


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("Доступ закрито.")
        return
    conversation_history[user_id] = []
    await update.message.reply_text(
        "Привіт! Я твій Claude асистент.\n\n"
        "Просто пиши мені — я відповім.\n"
        "/clear — очистити історію розмови\n"
        "/help — допомога"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return
    conversation_history[user_id] = []
    await update.message.reply_text("Історію очищено. Починаємо спочатку.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — почати розмову\n"
        "/clear — очистити історію\n"
        "/help — ця підказка"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("Доступ закрито.")
        return

    user_text = update.message.text
    if not user_text:
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING
    )

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "content": user_text
    })

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=conversation_history[user_id]
        )

        reply = response.content[0].text

        conversation_history[user_id].append({
            "role": "assistant",
            "content": reply
        })

        if len(reply) <= 4096:
            await update.message.reply_text(reply)
        else:
            for i in range(0, len(reply), 4096):
                await update.message.reply_text(reply[i:i+4096])

    except Exception as e:
        await update.message.reply_text(f"Помилка: {str(e)}")


async def main():
    # Запустити HTTP сервер в окремому потоці
    thread = threading.Thread(target=run_health_server, daemon=True)
    thread.start()
    print(f"Health server запущено на порту {PORT}")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущено...")

    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
