import os
import json
import threading
import telebot
from flask import Flask

# --- 1. НАСТРОЙКА FLASK (Для прохождения проверки портов хостинга) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает стабильно внутри Docker!", 200

def run_flask():
    # Хостинги автоматически передают нужный порт в переменную PORT
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- 2. ИНИЦИАЛИЗАЦИЯ БОТА И ПЕРЕМЕННЫХ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))

bot = telebot.TeleBot(BOT_TOKEN)

saved_templates = []
active_links = {} # {ссылка: {"name": имя_поста, "clicks": кол-во}}


# --- 3. СЛУЖЕБНЫЕ ФУНКЦИИ (Синхронизация через лог-чат) ---
def parse_report_message(text):
    global saved_templates, active_links
    try:
        if "--- СЛУЖЕБНЫЕ ДАННЫЕ ---" in text:
            json_data = text.split("--- СЛУЖЕБНЫЕ ДАННЫЕ ---")[1].strip()
            data = json.loads(json_data)
            saved_templates = data.get("templates", [])
            active_links = data.get("links", {})
    except Exception as e:
        print(f"Ошибка чтения данных из отчета: {e}")

def update_log_report():
    text_report = "📊 **ОТЧЕТ РАБОТЫ БОТА (DOCKER)**\n\n"
    
    text_report += "📝 **Текущие шаблоны ссылок:**\n"
    if saved_templates:
        for i, t in enumerate(saved_templates, 1):
            text_report += f"{i}. {t['text'][:30]}...\n"
    else:
        text_report += "_Нет активных шаблонов (отправьте текст в ЛС боту)_\n"
        
    text_report += "\n📈 **Статистика переходов по постам:**\n"
    total_clicks = 0
    if active_links:
        for link, info in active_links.items():
            text_report += f"🔗 {info['name']}: {info['clicks']} чел. ({link})\n"
            total_clicks += info['clicks']
        text_report += f"\n**Всего переходов:** {total_clicks} чел.\n"
    else:
        text_report += "_Постов со ссылками пока не создано_\n"
        
    service_data = {"templates": saved_templates, "links": active_links}
    final_text = f"{text_report}\n\n`--- СЛУЖЕБНЫЕ ДАННЫЕ ---`\n`{json.dumps(service_data)}`"

    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        
        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            bot.edit_message_text(chat_id=LOG_CHAT_ID, message_id=pinned_msg.message_id, text=final_text, parse_mode="Markdown")
        else:
            msg = bot.send_message(LOG_CHAT_ID, final_text, parse_mode="Markdown")
            bot.pin_chat_message(LOG_CHAT_ID, msg.message_id)
    except Exception as e:
        print(f"Ошибка обновления отчета в Telegram: {e}")

def sync_from_telegram():
    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            parse_report_message(pinned_msg.text)
            print("Данные восстановлены!")
    except Exception as e:
        print(f"Не удалось синхронизировать данные при старте: {e}")

sync_from_telegram()


# --- 4. ОБРАБОТКА КОМАНД В ЛС БОТА ---
@bot.message_handler(chat_types=['private'])
def handle_private_messages(message):
    global saved_templates
    
    if message.text == "/clear":
        saved_templates.clear()
        update_log_report()
        bot.reply_to(message, "Все шаблоны ссылок успешно удалены!")
        return
        
    if message.text == "/stats":
        sync_from_telegram()
        total = sum(info['clicks'] for info in active_links.values())
        bot.reply_to(message, f"📈 Всего переходов по ссылкам: **{total}**", parse_mode="Markdown")
        return

    saved_templates.append({
        "text": message.text,
        "entities": [e.__dict__ for e in message.entities] if message.entities else []
    })
    update_log_report()
    bot.reply_to(message, f"Шаблон сохранен! Всего в буфере: {len(saved_templates)}")


# --- 5. ОБРАБОТКА ПОСТОВ В КАНАЛЕ ---
@bot.channel_post_handler(content_types=['photo', 'video'])
def handle_channel_post(message):
    if message.chat.id != CHANNEL_ID or not saved_templates:
        return
        
    try:
        post_label = f"Пост №{message.message_id}"
        invite_obj = bot.create_chat_invite_link(chat_id=CHANNEL_ID, name=post_label)
        active_links[invite_obj.invite_link] = {"name": post_label, "clicks": 0}
        update_log_report()
    except Exception as e:
        print(f"Не удалось сгенерировать ссылку: {e}")
        return

    links_header = f"👉 [ПОДПИСАТЬСЯ НА КАНАЛ]({invite_obj.invite_link})\n\n"
    original_caption = message.caption if message.caption else ""
    final_caption = f"{links_header}{original_caption}"

    try:
        bot.edit_message_caption(chat_id=message.chat.id, message_id=message.message_id, caption=final_caption, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка изменения поста: {e}")


# --- 6. ОТСЛЕЖИВАНИЕ НОВЫХ ПОДПИСЧИКОВ ---
@bot.chat_member_handler()
def chat_member_updates(update):
    global active_links
    if update.new_chat_member.status == "member" and update.old_chat_member.status in ["left", "kicked", "left_chat_member"]:
        invite_link_obj = update.invite_link
        
        if invite_link_obj and invite_link_obj.invite_link:
            sync_from_telegram()
            link_str = invite_link_obj.invite_link
            if link_str in active_links:
                active_links[link_str]["clicks"] += 1
                update_log_report()


# --- 7. ЗАПУСК БОТА И ФЛАСКА ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print("Бот успешно запущен в Docker-контейнере!")
    bot.infinity_polling(allowed_updates=["message", "channel_post", "chat_member"])
