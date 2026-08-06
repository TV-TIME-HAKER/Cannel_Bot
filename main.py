import os
import json
import threading
import time
import telebot
from flask import Flask

# --- 1. НАСТРОЙКА FLASK (Для прохождения проверки Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Центральный Мультибот работает, всё помнит и заполняет пропущенные посты!", 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- 2. ГЛОБАЛЬНЫЕ НАСТРОЙКИ ГЛАВНОГО БОТА (ОТЦА) ---
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN")  
MAIN_ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  
MAIN_CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))  
MAIN_LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))   

main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)

# Структура базы данных в памяти
system_data = {
    "main_templates": [], 
    "bots": {},           
    "user_states": {} 
}

active_bot_instances = {}
processed_albums = set()


# --- 3. СИНХРОНИЗАЦИЯ ЧЕРЕЗ ТЕЛЕГРАМ (Вечная память) ---

def get_saved_msg_id():
    """Достает ID сообщения-базы из описания бота."""
    try:
        desc = main_bot.get_my_description().description
        if "DB_MSG_ID:" in desc:
            msg_id = desc.split("DB_MSG_ID:")[-1].strip().split()[0]
            if msg_id.isdigit():
                return int(msg_id)
    except Exception as e:
        print(f"[Система] Ошибка чтения ID базы из описания: {e}")
    return None

def save_system_state():
    """Сохраняет всю структуру сети в закреп лога Отца и прописывает ID в бота."""
    text_report = "👑 **ЦЕНТРАЛЬНАЯ СЕТЬ МУЛЬТИБОТОВ 1.1**\n\n"
    text_report += f"📝 Шаблонов Отца в шапке: {len(system_data['main_templates'])}\n"
    text_report += f"🤖 Дополнительных ботов в системе: {len(system_data['bots'])}\n\n"
    
    for token, info in system_data['bots'].items():
        masked_token = token[:10] + "..." + token[-5:]
        admin_info = f"`{info['admin_id']}`" if info.get("admin_id") else "_Ожидает админа_"
        text_report += f"🔹 Бот: `{masked_token}`\n├ Канал: `{info['channel_id']}`\n├ Лог: `{info['log_chat_id']}`\n└ Админ: {admin_info}\n\n"

    payload = {
        "main_templates": system_data["main_templates"],
        "bots": system_data["bots"]
    }
    final_text = f"{text_report}\n\n`--- СЛУЖЕБНЫЕ ДАННЫЕ ---`\n`{json.dumps(payload)}`"

    db_msg_id = get_saved_msg_id()
    msg = None

    try:
        if db_msg_id:
            try:
                msg = main_bot.edit_message_text(chat_id=MAIN_LOG_CHAT_ID, message_id=db_msg_id, text=final_text, parse_mode="Markdown")
            except Exception:
                msg = None

        if not msg:
            msg = main_bot.send_message(MAIN_LOG_CHAT_ID, final_text, parse_mode="Markdown")
            try:
                main_bot.pin_chat_message(MAIN_LOG_CHAT_ID, msg.message_id)
            except Exception:
                pass
            main_bot.set_my_description(f"Система мультиботов активна.\nDB_MSG_ID: {msg.message_id}")
            
    except Exception as e:
        print(f"[Система] Критическая ошибка сохранения состояния: {e}")

def update_child_log_report(token):
    """Обновляет персональный лог-чат конкретного бота-сына."""
    bot_config = system_data["bots"].get(token)
    if not bot_config or not bot_config.get("log_chat_id"):
        return

    child_bot = telebot.TeleBot(token)
    text_report = "📝 **АКТУАЛЬНАЯ ШАПКА ДЛЯ ЭТОГО КАНАЛА:**\n\n"
    
    if bot_config["templates"]:
        for i, t in enumerate(bot_config["templates"], 1):
            text_report += f"{i}. {t['text'][:40]}...\n"
    else:
        text_report += "_Шапка пуста. Отправьте анкоры этому боту в ЛС._\n"

    admin_status = f"`{bot_config['admin_id']}`" if bot_config.get("admin_id") else "_Не назначен_"
    final_text = f"{text_report}\n\n`--- ДАННЫЕ БОТА ---`\n`Хозяин бота: {admin_status}`\n`Шаблонов: {len(bot_config['templates'])}`"

    child_msg_id = bot_config.get("child_msg_id")
    msg = None

    try:
        if child_msg_id:
            try:
                msg = child_bot.edit_message_text(chat_id=bot_config["log_chat_id"], message_id=child_msg_id, text=final_text, parse_mode="Markdown")
            except Exception:
                msg = None

        if not msg:
            msg = child_bot.send_message(bot_config["log_chat_id"], final_text, parse_mode="Markdown")
            try:
                child_bot.pin_chat_message(bot_config["log_chat_id"], msg.message_id)
            except Exception:
                pass
            bot_config["child_msg_id"] = msg.message_id
            save_system_state() 
    except Exception as e:
        print(f"[{token[:5]}] Ошибка обновления лог-чата сына: {e}")


# --- 4. ФУНКЦИЯ ДЛЯ ЗАПОЛНЕНИЯ ПРОПУЩЕННЫХ ПОСТОВ (АНТИ-СПЯЧКА) ---

def fix_missing_posts(bot_instance, channel_id, templates):
    """Фоновая функция, которая находит посты без шапки и обновляет их."""
    if not templates or not channel_id:
        return
        
    try:
        # Запрашиваем последние 50 постов для глубокой проверки истории
        history = bot_instance.get_chat_history(chat_id=channel_id, limit=50)
        if not history:
            return

        anchor_texts = [t["text"] for t in templates if t.get("text")]
        if not anchor_texts:
            return

        # Локальный набор для отслеживания уже обработанных альбомов ВНУТРИ этой проверки
        local_processed_albums = set()

        for message in history:
            if message.content_type in ['photo', 'video']:
                # Если это альбом и мы его уже обрабатывали в этом цикле — строго пропускаем
                if message.media_group_id:
                    if message.media_group_id in local_processed_albums:
                        continue
                    local_processed_albums.add(message.media_group_id)

                current_caption = message.caption if message.caption else ""
                
                # Проверяем, есть ли ХОТЯ БЫ ОДИН наш анкор в тексте поста
                has_anchor = any(anchor in current_caption for anchor in anchor_texts)
                
                if not has_anchor:
                    print(f"[Фон] Исправляю пропущенный пост №{message.message_id} в канале {channel_id}...")
                    
                    links_header = ""
                    final_entities = []

                    for template in templates:
                        if template.get("text"):
                            current_offset = len(links_header)
                            links_header += template["text"] + "\n"
                            if template.get("entities"):
                                for ent_dict in template.get("entities"):
                                    ent = telebot.types.MessageEntity.de_json(ent_dict)
                                    ent.offset += current_offset
                                    final_entities.append(ent)
                                    
                    links_header += "\n"
                    caption_offset = len(links_header)
                    final_caption = f"{links_header}{current_caption}"
                    
                    if message.caption_entities:
                        for ent in message.caption_entities:
                            ent.offset += caption_offset
                            final_entities.append(ent)

                    try:
                        bot_instance.edit_message_caption(
                            chat_id=channel_id, 
                            message_id=message.message_id,
                            caption=final_caption, 
                            caption_entities=final_entities
                        )
                        # Пауза 5 секунд, чтобы Telegram не заблокировал за флуд
                        time.sleep(5)
                    except Exception as edit_err:
                        print(f"[Фон] Ошибка редактирования поста №{message.message_id}: {edit_err}")
                        time.sleep(10)
                        
    except Exception as e:
        print(f"[Фон] Ошибка при проверке истории канала {channel_id}: {e}")

def run_background_fixer():
    """Запускает циклическую проверку пропущенных постов для всей сети."""
    time.sleep(30)
    while True:
        try:
            if system_data.get("main_templates") and MAIN_CHANNEL_ID:
                fix_missing_posts(main_bot, MAIN_CHANNEL_ID, system_data["main_templates"])
                
            for token, config in list(system_data.get("bots", {}).items()):
                if config.get("templates") and config.get("channel_id"):
                    child_bot_temp = telebot.TeleBot(token)
                    fix_missing_posts(child_bot_temp, config["channel_id"], config["templates"])
                    
        except Exception as e:
            print(f"[Фон] Ошибка в общем цикле фиксации: {e}")
            
        time.sleep(300)

@main_bot.message_handler(commands=['check_missing'], chat_types=['private'])
def main_check_missing(message):
    if not is_main_admin(message): return
    if not MAIN_CHANNEL_ID or not system_data["main_templates"]:
        main_bot.reply_to(message, "Ошибка: Канал или шаблоны Отца не настроены.")
        return

    main_bot.reply_to(message, "🔍 Начинаю сканирование последних 50 постов основного канала...")
    
    try:
        history = main_bot.get_chat_history(chat_id=MAIN_CHANNEL_ID, limit=50)
        anchor_texts = [t["text"] for t in system_data["main_templates"] if t.get("text")]
        
        missing_ids = []
        local_processed = set()

        for msg in history:
            if msg.content_type in ['photo', 'video']:
                if msg.media_group_id:
                    if msg.media_group_id in local_processed: continue
                    local_processed.add(msg.media_group_id)

                caption = msg.caption if msg.caption else ""
                if not any(anchor in caption for anchor in anchor_texts):
                    missing_ids.append(f"Пост №{msg.message_id}")

        if missing_ids:
            res = "⚠️ **Найдены пропущенные постов без шапки:**\n\n" + "\n".join(missing_ids)
            res += "\n\n_Фоновый фиксер исправит их автоматически в течение нескольких минут._"
        else:
            res = "✅ **Всё чисто!** Последние 50 постов проверены, во всех есть актуальная рекламная шапка."
            
        main_bot.reply_to(message, res, parse_mode="Markdown")
    except Exception as e:
        main_bot.reply_to(message, f"❌ Ошибка сканирования: {e}")
        
    # --- 5. ДВИЖОК ДЛЯ БОТОВ-СЫНОВЕЙ ---
def child_bot_worker(token):
    bot = telebot.TeleBot(token)
    
    @bot.channel_post_handler(content_types=['photo', 'video'])
    def handle_child_channel_post(message):
        bot_config = system_data["bots"].get(token)
        if not bot_config or message.chat.id != bot_config["channel_id"] or not bot_config["templates"]:
            return

        if message.media_group_id:
            if message.media_group_id in processed_albums: return
            processed_albums.add(message.media_group_id)
            if len(processed_albums) > 200: processed_albums.clear()

        links_header = ""
        final_entities = []

        for template in bot_config["templates"]:
            if template["text"]:
                current_offset = len(links_header)
                links_header += template["text"] + "\n"
                if template["entities"]:
                    for ent_dict in template["entities"]:
                        ent = telebot.types.MessageEntity.de_json(ent_dict)
                        ent.offset += current_offset
                        final_entities.append(ent)
                        
        links_header += "\n"
        original_caption = message.caption if message.caption else ""
        caption_offset = len(links_header)
        final_caption = f"{links_header}{original_caption}"
        
        if message.caption_entities:
            for ent in message.caption_entities:
                ent.offset += caption_offset
                final_entities.append(ent)

        try:
            bot.edit_message_caption(
                chat_id=message.chat.id, message_id=message.message_id,
                caption=final_caption, caption_entities=final_entities
            )
        except Exception as e:
            print(f"[{token[:5]}] Ошибка изменения поста: {e}")

    @bot.message_handler(chat_types=['private'])
    def handle_child_private(message):
        bot_config = system_data["bots"].get(token)
        if not bot_config: return

        user_id = message.from_user.id

        if message.text == "/start":
            if not bot_config.get("admin_id"):
                bot_config["admin_id"] = user_id
                save_system_state()
                update_child_log_report(token)
                bot.reply_to(message, "👑 **Вы успешно авторизованы как хозяин этого бота!**\n\nОтправляйте мне анкоры для вашего канала.")
                return
            
            if bot_config["admin_id"] != user_id:
                bot.reply_to(message, "❌ У этого бота уже есть хозяин.")
                return

            bot.reply_to(message, f"🟢 Бот работает!\nКанал: `{bot_config['channel_id']}`\nСтрок в шапке: {len(bot_config['templates'])}", parse_mode="Markdown")
            return

        if bot_config.get("admin_id") != user_id:
            return

        if message.text == "/clear":
            bot_config["templates"].clear()
            save_system_state()
            update_child_log_report(token)
            bot.reply_to(message, "🗑️ Шапка этого канала очищена!")
            return
        if message.text == "/check_missing":
            if not bot_config.get("channel_id") or not bot_config["templates"]:
                bot.reply_to(message, "Ошибка: Настройки этого бота пусты.")
                return

            bot.reply_to(message, "🔍 Сканирую историю этого канала...")
            try:
                history = bot.get_chat_history(chat_id=bot_config["channel_id"], limit=50)
                anchor_texts = [t["text"] for t in bot_config["templates"] if t.get("text")]
                
                missing_ids = []
                local_processed = set()

                for msg in history:
                    if msg.content_type in ['photo', 'video']:
                        if msg.media_group_id:
                            if msg.media_group_id in local_processed: continue
                            local_processed.add(msg.media_group_id)

                        caption = msg.caption if msg.caption else ""
                        if not any(anchor in caption for anchor in anchor_texts):
                            missing_ids.append(f"Пост №{msg.message_id}")

                if missing_ids:
                    res = "⚠️ **Пропущенные посты в этом канале:**\n\n" + "\n".join(missing_ids)
                else:
                    res = "✅ **Всё отлично!** В этом канале пропущенных постов не обнаружено."
                bot.reply_to(message, res, parse_mode="Markdown")
            except Exception as e:
                bot.reply_to(message, f"Ошибка: {e}")
            return

        bot_config["templates"].append({
            "text": message.text,
            "entities": [e.__dict__ for e in message.entities] if message.entities else []
        })
        save_system_state()
        update_child_log_report(token)
        bot.reply_to(message, f"✅ Анкор добавлен! Всего строк: {len(bot_config['templates'])}")

    try:
        bot.infinity_polling(allowed_updates=["message", "channel_post"])
    except Exception as e:
        print(f"Ошибка пуллинга бота {token[:5]}: {e}")

def start_child_bot_thread(token):
    if token in active_bot_instances: return
    t = threading.Thread(target=child_bot_worker, args=(token,))
    t.daemon = True
    t.start()
    active_bot_instances[token] = t

# --- 6. ЛОГИКА ГЛАВНОГО БОТА (ОТЦА) ДЛЯ ОСНОВНОГО КАНАЛА И СЕТИ ---
def is_main_admin(message):
    return message.from_user.id == MAIN_ADMIN_ID

@main_bot.channel_post_handler(content_types=['photo', 'video'])
def handle_main_channel_post(message):
    if message.chat.id != MAIN_CHANNEL_ID or not system_data["main_templates"]:
        return

    if message.media_group_id:
        if message.media_group_id in processed_albums: return
        processed_albums.add(message.media_group_id)
        if len(processed_albums) > 200: processed_albums.clear()

    links_header = ""
    final_entities = []

    for template in system_data["main_templates"]:
        if template["text"]:
            current_offset = len(links_header)
            links_header += template["text"] + "\n"
            if template["entities"]:
                for ent_dict in template["entities"]:
                    ent = telebot.types.MessageEntity.de_json(ent_dict)
                    ent.offset += current_offset
                    final_entities.append(ent)
                    
    links_header += "\n"
    original_caption = message.caption if message.caption else ""
    caption_offset = len(links_header)
    final_caption = f"{links_header}{original_caption}"
    
    if message.caption_entities:
        for ent in message.caption_entities:
            ent.offset += caption_offset
            final_entities.append(ent)

    try:
        main_bot.edit_message_caption(
            chat_id=message.chat.id, message_id=message.message_id,
            caption=final_caption, caption_entities=final_entities
        )
    except Exception as e:
        print(f"[Отец] Ошибка изменения поста: {e}")

@main_bot.message_handler(commands=['start'], chat_types=['private'])
def main_welcome(message):
    if not is_main_admin(message): return
    main_bot.reply_to(
        message,
        "👑 **Панель Отца Ботов (Основной канал)**\n\n"
        "📜 **Управление шапкой Отца:**\n"
        "• Отправьте мне анкор в ЛС — он встанет в шапку вашего основного канала.\n"
        "• Команда `/clear` — очистит шапку основного канала.\n"
        "• Команда `/check_missing` — проверить пропущенные посты.\n\n"
        "🌐 **Управление другими ботами:**\n"
        "➕ `/add_bot` — подключить нового бота в сеть\n"
        "❌ `/delete_bot` — удалить бота из сети\n"
        "📋 `/list` — список всех запущенных ботов\n",
        parse_mode="Markdown"
    )

@main_bot.message_handler(commands=['list'], chat_types=['private'])
def main_list(message):
    if not is_main_admin(message): return
    if not system_data["bots"]:
        main_bot.reply_to(message, "Второстепенных ботов в сети нет.")
        return
    res = "📋 **Список ботов в сети:**\n\n"
    for token, info in system_data["bots"].items():
        admin_info = f"`{info['admin_id']}`" if info.get("admin_id") else "_Ожидает активации_"
        res += f"🤖 `{token[:10]}...`\n├ Канал: `{info['channel_id']}`\n└ Admin: {admin_info}\n\n"
    main_bot.reply_to(message, res, parse_mode="Markdown")

@main_bot.message_handler(commands=['check_missing'], chat_types=['private'])
def main_check_missing(message):
    if not is_main_admin(message): return
    if not MAIN_CHANNEL_ID or not system_data["main_templates"]:
        main_bot.reply_to(message, "Ошибка: Канал или шаблоны Отца не настроены.")
        return

    main_bot.reply_to(message, "🔍 Начинаю сканирование последних 50 постов основного канала...")
    
    try:
        history = main_bot.get_chat_history(chat_id=MAIN_CHANNEL_ID, limit=50)
        anchor_texts = [t["text"] for t in system_data["main_templates"] if t.get("text")]
        
        missing_ids = []
        local_processed = set()

        for msg in history:
            if msg.content_type in ['photo', 'video']:
                if msg.media_group_id:
                    if msg.media_group_id in local_processed: continue
                    local_processed.add(msg.media_group_id)

                caption = msg.caption if msg.caption else ""
                if not any(anchor in caption for anchor in anchor_texts):
                    missing_ids.append(f"Пост №{msg.message_id}")

        if missing_ids:
            res = "⚠️ **Найдены пропущенные посты без шапки:**\n\n" + "\n".join(missing_ids)
            res += "\n\n_Фоновый фиксер исправит их автоматически в течение нескольких минут._"
        else:
            res = "✅ **Всё чисто!** Последние 50 постов проверены, во всех есть актуальная рекламная шапка."
            
        main_bot.reply_to(message, res, parse_mode="Markdown")
    except Exception as e:
        main_bot.reply_to(message, f"❌ Ошибка сканирования: {e}")

@main_bot.message_handler(commands=['add_bot'], chat_types=['private'])
def main_add_bot(message):
    if not is_main_admin(message): return
    system_data["user_states"][message.from_user.id] = {"step": "waiting_token"}
    main_bot.reply_to(message, "Шаг 1: Отправьте **API Token** нового бота из @BotFather.")

@main_bot.message_handler(commands=['delete_bot'], chat_types=['private'])
def main_delete_bot(message):
    if not is_main_admin(message): return
    system_data["user_states"][message.from_user.id] = {"step": "waiting_delete_token"}
    main_bot.reply_to(message, "Отправьте API Токен бота для удаления.")

@main_bot.message_handler(chat_types=['private'])
def main_router(message):
    if not is_main_admin(message): return
    user_id = message.from_user.id
    state = system_data["user_states"].get(user_id)
    
    if not state:
        if message.text == "/clear":
            system_data["main_templates"].clear()
            save_system_state()
            main_bot.reply_to(message, "🗑️ Шапка основного канала Отца полностью очищена!")
            return
            
        system_data["main_templates"].append({
            "text": message.text,
            "entities": [e.__dict__ for e in message.entities] if message.entities else []
        })
        save_system_state()
        main_bot.reply_to(message, f"✅ Анкор добавлен в основной канал Отца! Всего строк: {len(system_data['main_templates'])}")
        return

    if state["step"] == "waiting_token":
        token = message.text.strip()
        if token == MAIN_BOT_TOKEN:
            main_bot.reply_to(message, "⚠️ Токен Отца нельзя добавлять через /add_bot.")
            del system_data["user_states"][user_id]
            return
        state["temp_token"] = token
        state["step"] = "waiting_channel"
        main_bot.reply_to(message, "✅ Токен принят.\n\nШаг 2: Отправьте **ID КАНАЛА** (со знаком минус).")
        return

    if state["step"] == "waiting_channel":
        try:
            state["temp_channel"] = int(message.text.strip())
            state["step"] = "waiting_log"
            main_bot.reply_to(message, "✅ ID канала принят.\n\nШаг 3: Отправьте **ID ЛОГ-ЧАТА** для этого бота.")
        except ValueError:
            main_bot.reply_to(message, "Ошибка! Нужен цифровой ID. Попробуйте еще раз:")
        return

    if state["step"] == "waiting_log":
        try:
            log_id = int(message.text.strip())
            token = state["temp_token"]
            
            system_data["bots"][token] = {
                "channel_id": state["temp_channel"],
                "log_chat_id": log_id,
                "admin_id": None,
                "child_msg_id": None,
                "templates": []
            }
            
            save_system_state()
            update_child_log_report(token) 
            start_child_bot_thread(token)
            
            del system_data["user_states"][user_id]
            main_bot.reply_to(message, "🎉 **Бот успешно добавлен в сеть!**\n\nПерейдите к нему в ЛС со второго аккаунта и нажмите `/start`.")
        except ValueError:
            main_bot.reply_to(message, "Ошибка! Нужен цифровой ID. Попробуйте еще раз:")
        return

    if state["step"] == "waiting_delete_token":
        token = message.text.strip()
        if token in system_data["bots"]:
            del system_data["bots"][token]
            save_system_state()
            del system_data["user_states"][user_id]
            main_bot.reply_to(message, "🗑️ Бот удален из базы.")
        else:
            main_bot.reply_to(message, "❌ Токен не найден.")
        return


if __name__ == "__main__":
    load_and_start_system()
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    fixer_thread = threading.Thread(target=run_background_fixer)
    fixer_thread.daemon = True
    fixer_thread.start()
    
    print("Центральный мультибот полностью готов к работе и запущен!")
    main_bot.infinity_polling(allowed_updates=["message", "channel_post"])
