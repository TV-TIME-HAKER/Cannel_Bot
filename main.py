import os
import json
import threading
import telebot
from flask import Flask

# --- 1. НАСТРОЙКА FLASK (Чтобы Render видел "сайт" и работал бесплатно) ---
app = Flask(__name__)


@app.route('/')
def home():
    return "Бот работает стабильно и бесплатно!", 200


def run_flask():
    # Render автоматически передает нужный порт в переменную PORT
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- 2. ИНИЦИАЛИЗАЦИЯ БОТА И ПЕРЕМЕННЫХ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))

bot = telebot.TeleBot(BOT_TOKEN)

# Временные буферы в памяти (будут восстанавливаться из Telegram при перезапуске)
saved_templates = []
active_links = {}  # Структура: {ссылка: {"name": имя_поста, "clicks": кол-во}}


# --- 3. СЛУЖЕБНЫЕ ФУНКЦИИ (Синхронизация через лог-чат) ---
def parse_report_message(text):
    """Извлекает скрытые JSON-данные из закрепленного сообщения."""
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
    """Обновляет или создает ОДНО закрепленное сообщение со статистикой."""
    text_report = "📊 **ОТЧЕТ РАБОТЫ БОТА**\n\n"

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

    # Прячем JSON со структурой данных в самый низ сообщения
    service_data = {"templates": saved_templates, "links": active_links}
    final_text = f"{text_report}\n\n`--- СЛУЖЕБНЫЕ ДАННЫЕ ---`\n`{json.dumps(service_data)}`"

    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message

        # Если закреп от бота уже есть — редактируем его, чтобы не спамить
        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            bot.edit_message_text(chat_id=LOG_CHAT_ID, message_id=pinned_msg.message_id, text=final_text,
                                  parse_mode="Markdown")
        else:
            # Если закрепа нет — создаем новый и закрепляем
            msg = bot.send_message(LOG_CHAT_ID, final_text, parse_mode="Markdown")
            bot.pin_chat_message(LOG_CHAT_ID, msg.message_id)
    except Exception as e:
        print(f"Ошибка обновления отчета в Telegram: {e}")


def sync_from_telegram():
    """Скачивает последнее состояние бота из Telegram при старте сервера."""
    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            parse_report_message(pinned_msg.text)
            print("Данные успешно восстановлены из лог-чата!")
    except Exception as e:
        print(f"Не удалось синхронизировать данные при старте: {e}")


# Синхронизируем память бота с Telegram сразу при запуске скрипта
sync_from_telegram()


# --- 4. ОБРАБОТКА КОМАНД И НАСТРОЕК В ЛС БОТА ---
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
        bot.reply_to(message, f"📈 Всего переходов по ссылкам во все время: **{total}**", parse_mode="Markdown")
        return

    # Сохраняем присланный текст/ссылку как шаблон
    saved_templates.append({
        "text": message.text,
        "entities": [e.__dict__ for e in message.entities] if message.entities else []
    })
    update_log_report()
    bot.reply_to(message, f"Шаблон сохранен! Всего шаблонов в буфере: {len(saved_templates)}")


# --- 5. ОБРАБОТКА ПОСТОВ В КАНАЛЕ ---
# --- 5. ОБРАБОТКА ПОСТОВ В КАНАЛЕ ---
@bot.channel_post_handler(content_types=['photo', 'video'])
def handle_channel_post(message):
    # Работаем только с нашим целевым каналом и только если есть сохраненные ссылки
    if message.chat.id != CHANNEL_ID or not saved_templates:
        return

    try:
        # Создаем уникальную пригласительную ссылку Telegram для этого поста
        post_label = f"Пост №{message.message_id}"
        invite_obj = bot.create_chat_invite_link(chat_id=CHANNEL_ID, name=post_label)

        # Добавляем ссылку в систему учета и обновляем лог-чат
        active_links[invite_obj.invite_link] = {"name": post_label, "clicks": 0}
        update_log_report()
    except Exception as e:
        print(f"Не удалось сгенерировать ссылку: {e}")
        return

    # Собираем динамическую шапку из сохраненных анкоров
    links_header = ""
    final_entities = []

    # 1. Поочередно добавляем ваши присланные анкоры друг за другом с новой строки
    for template in saved_templates:
        if template["text"]:
            current_offset = len(links_header)
            links_header += template["text"] + "\n"

            # Переносим синие ссылки (entities), сдвигая их под новую длину строки
            if template["entities"]:
                for ent_dict in template["entities"]:
                    # Восстанавливаем объект сущности из сохраненного словаря
                    ent = telebot.types.MessageEntity.de_json(ent_dict)
                    ent.offset += current_offset
                    final_entities.append(ent)

    # Добавляем пустую строку-разделитель между шапкой и основным текстом
    links_header += "\n"

    # 2. Добавляем оригинальный текст поста (описание к фото/видео)
    original_caption = message.caption if message.caption else ""
    caption_offset = len(links_header)
    final_caption = f"{links_header}{original_caption}"

    # Переносим родные сущности оригинального текста (если в посте были свои ссылки или хэштеги)
    if message.caption_entities:
        for ent in message.caption_entities:
            ent.offset += caption_offset
            final_entities.append(ent)

    try:
        # Редактируем подпись к фото/видео в канале
        # ВНИМАНИЕ: убираем parse_mode="Markdown", так как теперь мы передаем точные caption_entities
        bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=message.message_id,
            caption=final_caption,
            caption_entities=final_entities
        )
    except Exception as e:
        print(f"Ошибка автоматического изменения поста: {e}")


# --- 6. ОТСЛЕЖИВАНИЕ НОВЫХ ПОДПИСЧИКОВ ---
@bot.chat_member_handler()
def chat_member_updates(update):
    global active_links
    # Проверяем, что пользователь именно вступил в канал, а не вышел
    if update.new_chat_member.status == "member" and update.old_chat_member.status in ["left", "kicked",
                                                                                       "left_chat_member"]:
        invite_link_obj = update.invite_link

        if invite_link_obj and invite_link_obj.invite_link:
            # Обновляем данные из Telegram на случай, если сервер перезапускался
            sync_from_telegram()

            link_str = invite_link_obj.invite_link
            if link_str in active_links:
                active_links[link_str]["clicks"] += 1
                # Сохраняем измененный счетчик кликов в закрепленный отчет
                update_log_report()


# --- 7. ЗАПУСК БОТА И ФЛАСКА В ДВА ПОТОКА ---
if __name__ == "__main__":
    # Шаг 1: Запускаем Flask веб-сервер в фоновом режиме для обхода ограничений Render
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Шаг 2: Запускаем бесконечный опрос Telegram в основном потоке
    print("Бот успешно запущен на бесплатном тарифе Web Service!")
    bot.infinity_polling(allowed_updates=["message", "channel_post", "chat_member"])