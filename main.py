import os
import json
import threading
import telebot
from flask import Flask

# --- 1. НАСТРОЙКА FLASK (Для прохождения проверки Render) ---
app = Flask(__name__)


@app.route('/')
def home():
    return "Бот работает стабильно, безопасно и бесплатно!", 200


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- 2. ИНИЦИАЛИЗАЦИЯ БОТА И ПЕРЕМЕННЫХ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))

# ВАЖНО: Укажите ваш Telegram ID (число) прямо тут или через переменную окружения
# Если хотите через Render, добавьте переменную ADMIN_ID. Если нет — просто замените os.getenv(...) на ваш ID, например: ADMIN_ID = 12345678
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = telebot.TeleBot(BOT_TOKEN)

# Временный буфер шаблонов (восстанавливается из лог-чата)
saved_templates = []


# --- 3. СЛУЖЕБНЫЕ ФУНКЦИИ (Сохранение шаблонов в лог-чат) ---
def parse_report_message(text):
    """Извлекает шаблоны из закрепленного сообщения после перезапуска."""
    global saved_templates
    try:
        if "--- СЛУЖЕБНЫЕ ДАННЫЕ ---" in text:
            json_data = text.split("--- СЛУЖЕБНЫЕ ДАННЫЕ ---")[1].strip()
            data = json.loads(json_data)
            saved_templates = data.get("templates", [])
    except Exception as e:
        print(f"Ошибка чтения данных из отчета: {e}")


def update_log_report():
    """Обновляет закрепленный список шаблонов в лог-чате."""
    text_report = "📝 **АКТУАЛЬНАЯ ШАПКА ДЛЯ КАНАЛА:**\n\n"
    if saved_templates:
        for i, t in enumerate(saved_templates, 1):
            text_report += f"{i}. {t['text'][:40]}...\n"
    else:
        text_report += "_Шапка пуста. Отправьте анкоры боту в ЛС._\n"

    service_data = {"templates": saved_templates}
    final_text = f"{text_report}\n\n`--- СЛУЖЕБНЫЕ ДАННЫЕ ---`\n`{json.dumps(service_data)}`"

    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message

        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            bot.edit_message_text(chat_id=LOG_CHAT_ID, message_id=pinned_msg.message_id, text=final_text,
                                  parse_mode="Markdown")
        else:
            msg = bot.send_message(LOG_CHAT_ID, final_text, parse_mode="Markdown")
            bot.pin_chat_message(LOG_CHAT_ID, msg.message_id)
    except Exception as e:
        print(f"Ошибка обновления отчета в Telegram: {e}")


def sync_from_telegram():
    """Синхронизирует шаблоны при старте."""
    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            parse_report_message(pinned_msg.text)
            print("Шаблоны успешно восстановлены!")
    except Exception as e:
        print(f"Не удалось восстановить шаблоны при старте: {e}")


sync_from_telegram()


# --- 4. ОБРАБОТКА КОМАНД И ЛС (Доступ только для ADMIN_ID) ---

# Функция-фильтр: проверяет, от админа ли сообщение
def is_admin(message):
    return message.from_user.id == ADMIN_ID


@bot.message_handler(commands=['start'], chat_types=['private'])
def send_welcome(message):
    if not is_admin(message):
        bot.reply_to(message, "❌ Доступ ограничен. Вы не являетесь администратором этого бота. Усли вы Александр то ИДИ НАХУЙ НЕЧЕГО МНЕ ТУТ ШАБЛОНЫ ДОБАВЛЯТЬ")
        return

    bot.reply_to(
        message,
        "👋 **Привет, Босс! Бот успешно работает и готов к командам.**\n\n"
        "📜 **Как управлять шапкой:**\n"
        "1. Просто отправьте мне текст с синей ссылкой (анкор) — он добавится в шапку.\n"
        "2. Отправьте еще один — он встанет на следующую строку.\n"
        "3. Команда `/clear` — полностью очистит всю шапку.\n\n"
        "STATUS: 🟢 В СЕТИ (ONLINE)",
        parse_mode="Markdown"
    )


@bot.message_handler(chat_types=['private'])
def handle_private_messages(message):
    global saved_templates

    # Игнорируем всех, кроме админа
    if not is_admin(message):
        return

    if message.text == "/clear":
        saved_templates.clear()
        update_log_report()
        bot.reply_to(message, "🗑️ Вся рекламная шапка успешно очищена!")
        return

    # Сохраняем присланный анкор
    saved_templates.append({
        "text": message.text,
        "entities": [e.__dict__ for e in message.entities] if message.entities else []
    })
    update_log_report()
    bot.reply_to(message, f"✅ Анкор добавлен! Всего строк в шапке: {len(saved_templates)}")


# Измененный словарь для защиты от двойного срабатывания на один и тот же альбом
processed_albums = set()

# --- 5. ОБРАБОТКА ПОСТОВ В КАНАЛЕ (Добавление шапки) ---
@bot.channel_post_handler(content_types=['photo', 'video'])
def handle_channel_post(message):
    if message.chat.id != CHANNEL_ID or not saved_templates:
        return

    # Проверка: если это альбом (медиагруппа)
    if message.media_group_id:
        # Если мы уже обрабатываем этот альбом, пропускаем остальные фото из него,
        # так как подпись в Telegram всегда привязана только к первому файлу альбома.
        if message.media_group_id in processed_albums:
            return
        processed_albums.add(message.media_group_id)
        
        # Очищаем старые ID альбомов из памяти, чтобы она не переполнялась (храним последние 100)
        if len(processed_albums) > 100:
            processed_albums.pop()

    links_header = ""
    final_entities = []

    # Склеиваем сохраненные анкоры столбиком
    for template in saved_templates:
        if template["text"]:
            current_offset = len(links_header)
            links_header += template["text"] + "\n"
            
            if template["entities"]:
                for ent_dict in template["entities"]:
                    ent = telebot.types.MessageEntity.de_json(ent_dict)
                    ent.offset += current_offset
                    final_entities.append(ent)
                    
    links_header += "\n" # Отступ перед основным текстом
    
    original_caption = message.caption if message.caption else ""
    caption_offset = len(links_header)
    final_caption = f"{links_header}{original_caption}"
    
    if message.caption_entities:
        for ent in message.caption_entities:
            ent.offset += caption_offset
            final_entities.append(ent)

    try:
        # Редактируем подпись
        bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=message.message_id,
            caption=final_caption,
            caption_entities=final_entities
        )
    except Exception as e:
        print(f"Ошибка изменения поста в канале: {e}")



# --- 6. ЗАПУСК ВСЕЙ СИСТЕМЫ ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    print("Бот успешно обновлен и запущен!")
    bot.infinity_polling(allowed_updates=["message", "channel_post"])
