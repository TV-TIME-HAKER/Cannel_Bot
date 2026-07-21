import os
import json
import telebot

# Получаем настройки из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))  # ID вашего чата для отчетов

bot = telebot.TeleBot(BOT_TOKEN)

# Временные буферы в памяти (очищаются при перезапуске, но бот восстановит их из лог-чата)
saved_templates = []
active_links = {}  # {invite_link: {"name": str, "clicks": int}}


def parse_report_message(text):
    """
    Парсит текст из закрепленного сообщения, чтобы восстановить
    активные ссылки и шаблоны после перезапуска бота.
    """
    global saved_templates, active_links
    try:
        if "--- СЛУЖЕБНЫЕ ДАННЫЕ ---" in text:
            # Находим JSON-блок в самом низу сообщения
            json_data = text.split("--- СЛУЖЕБНЫЕ ДАННЫЕ ---")[1].strip()
            data = json.loads(json_data)
            saved_templates = data.get("templates", [])
            active_links = data.get("links", {})
    except Exception as e:
        print(f"Ошибка парсинга отчета: {e}")


def update_log_report():
    """
    Находит закрепленное сообщение в лог-чате, обновляет его текст и статистику.
    Если сообщения нет, создает новое и закрепляет его.
    """
    # Формируем красивый текст для админа
    text_report = "📊 **ОТЧЕТ РАБОТЫ БОТА**\n\n"

    text_report += "📝 **Текущие шаблоны ссылок:**\n"
    if saved_templates:
        for i, t in enumerate(saved_templates, 1):
            text_report += f"{i}. {t['text'][:30]}...\n"
    else:
        text_report += "_Нет активных шаблонов (добавьте в ЛС)_\n"

    text_report += "\n📈 **Статистика переходов по постам:**\n"
    total_clicks = 0
    if active_links:
        for link, info in active_links.items():
            text_report += f"🔗 {info['name']}: {info['clicks']} чел. ( {link} )\n"
            total_clicks += info['clicks']
        text_report += f"\n**Всего переходов:** {total_clicks} чел.\n"
    else:
        text_report += "_Постов со ссылками пока не создано_\n"

    # Вшиваем скрытый JSON в конец сообщения для сохранения состояния бота
    service_data = {
        "templates": saved_templates,
        "links": active_links
    }
    final_text = f"{text_report}\n\n`--- СЛУЖЕБНЫЕ ДАННЫЕ ---`\n`{json.dumps(service_data)}`"

    # Ищем закрепленное сообщение в чате
    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message

        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            # Если закрепленное сообщение от нашего бота уже есть — редактируем его
            bot.edit_message_text(
                chat_id=LOG_CHAT_ID,
                message_id=pinned_msg.message_id,
                text=final_text,
                parse_mode="Markdown"
            )
            return pinned_msg.message_id
        else:
            # Если закрепа нет, отправляем новое сообщение
            msg = bot.send_message(LOG_CHAT_ID, final_text, parse_mode="Markdown")
            bot.pin_chat_message(LOG_CHAT_ID, msg.message_id)
            return msg.message_id
    except Exception as e:
        print(f"Ошибка обновления отчета в лог-чате: {e}")
        return None


def sync_from_telegram():
    """Синхронизирует память бота со старым отчетом при старте сервера."""
    try:
        chat = bot.get_chat(LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == bot.get_me().id:
            parse_report_message(pinned_msg.text)
            print("Данные успешно восстановлены из лог-чата Telegram!")
    except Exception as e:
        print(f"Не удалось синхронизировать данные при старте: {e}")


# Синхронизируем данные сразу при запуске скрипта
sync_from_telegram()


# --- ОБРАБОТКА МЕССЕДЖЕЙ В ЛС ---
@bot.message_handler(chat_types=['private'])
def handle_private_messages(message):
    global saved_templates

    if message.text == "/clear":
        saved_templates.clear()
        update_log_report()
        bot.reply_to(message, "Все шаблоны ссылок удалены!")
        return

    if message.text == "/stats":
        # Бот просто пересылает актуальные цифры из лога
        sync_from_telegram()
        total = sum(info['clicks'] for info in active_links.values())
        bot.reply_to(message, f"📈 Всего переходов по ссылкам на данный момент: **{total}**", parse_mode="Markdown")
        return

    # Сохраняем шаблон
    saved_templates.append({
        "text": message.text,
        "entities": [e.__dict__ for e in message.entities] if message.entities else []
    })
    update_log_report()
    bot.reply_to(message, f"Шаблон сохранен! Всего шаблонов в буфере: {len(saved_templates)}")


# --- ОБРАБОТКА ПОСТОВ В КАНАЛЕ ---
@bot.channel_post_handler(content_types=['photo', 'video'])
def handle_channel_post(message):
    if message.chat.id != CHANNEL_ID or not saved_templates:
        return

    # Создаем официальную инвайт-ссылку Telegram под этот конкретный пост
    try:
        post_label = f"Пост №{message.message_id}"
        invite_obj = bot.create_chat_invite_link(chat_id=CHANNEL_ID, name=post_label)

        # Добавляем в оперативку и обновляем отчет в лог-чате
        active_links[invite_obj.invite_link] = {"name": post_label, "clicks": 0}
        update_log_report()
    except Exception as e:
        print(f"Не удалось сгенерировать инвайт-ссылку: {e}")
        return

    # Формируем новый текст для поста (Ссылки наверх, оригинальный текст вниз)
    links_header = ""
    # Для простоты зашиваем кликабельный текст с нашей новой инвайт-ссылкой
    # Вы можете поменять текст "👉 ПОДПИСАТЬСЯ НА КАНАЛ" на любой другой
    links_header += f"👉 [ПОДПИСАТЬСЯ НА КАНАЛ]({invite_obj.invite_link})\n\n"

    original_caption = message.caption if message.caption else ""
    final_caption = f"{links_header}{original_caption}"

    try:
        bot.edit_message_caption(
            chat_id=message.chat.id,
            message_id=message.message_id,
            caption=final_caption,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Ошибка изменения поста в канале: {e}")


# --- ОТСЛЕЖИВАНИЕ НОВЫХ ПОДПИСЧИКОВ ---
@bot.chat_member_handler()
def chat_member_updates(update):
    global active_links
    # Проверяем, что это именно вступление нового участника
    if update.new_chat_member.status == "member" and update.old_chat_member.status in ["left", "kicked",
                                                                                       "left_chat_member"]:
        invite_link_obj = update.invite_link

        if invite_link_obj and invite_link_obj.invite_link:
            # На всякий случай обновляем данные из закрепа, вдруг сервер только что перезагрузился
            sync_from_telegram()

            link_str = invite_link_obj.invite_link
            if link_str in active_links:
                active_links[link_str]["clicks"] += 1
                # Сохраняем обновленный счетчик в закрепленный отчет
                update_log_report()


if __name__ == "__main__":
    print("Бот успешно запущен на системе логов...")
    bot.infinity_polling(allowed_updates=["message", "channel_post", "chat_member"])
