import os
import json
import threading
import telebot
from flask import Flask

# --- 1. НАСТРОЙКА FLASK (Для прохождения проверки Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Центральная сеть мультиботов активна и полностью исправна!", 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- 2. ГЛОБАЛЬНЫЕ НАСТРОЙКИ ГЛАВНОГО БОТА (ОТЦА) ---
MAIN_BOT_TOKEN = os.getenv("BOT_TOKEN")  
MAIN_ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  
MAIN_CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))  # Первый канал Отца из секретов
MAIN_LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID"))   # Первый лог-чат Отца из секретов

main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)

# База данных системы в оперативной памяти
system_data = {
    "main_templates": [], # Шаблоны анкоров лично для Первого канала Отца
    "bots": {},           # { TOKEN: {"channel_id": int, "log_chat_id": int, "admin_id": int/None, "templates": [...] } }
    "user_states": {} 
}

active_bot_instances = {}
processed_albums = set()


# --- 3. СИНХРОНИЗАЦИЯ ЧЕРЕЗ ТЕЛЕГРАМ ЧАТЫ (Хранилище данных) ---
def save_system_state():
    """Сохраняет структуру всей сети и шаблоны Отца в закреп лога Отца."""
    text_report = "👑 **ЦЕНТРАЛЬНАЯ СЕТЬ МУЛЬТИБОТОВ**\n\n"
    text_report += f"📝 Шаблонов Отца в шапке: {len(system_data['main_templates'])}\n"
    text_report += f"🤖 Дополнительных ботов в системе: {len(system_data['bots'])}\n\n"
    
    for token, info in system_data['bots'].items():
        masked_token = token[:10] + "..." + token[-5:]
        admin_info = f"`{info['admin_id']}`" if info.get("admin_id") else "_Ожидает админа_"
        text_report += f"🔹 Бот: `{masked_token}`\n├ Канал: `{info['channel_id']}`\n└ Админ: {admin_info}\n\n"

    final_text = f"{text_report}\n\n`--- СЛУЖЕБНЫЕ ДАННЫЕ ---`\n`{json.dumps({'main_templates': system_data['main_templates'], 'bots': system_data['bots']})}`"

    try:
        chat = main_bot.get_chat(MAIN_LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == main_bot.get_me().id:
            main_bot.edit_message_text(chat_id=MAIN_LOG_CHAT_ID, message_id=pinned_msg.message_id, text=final_text, parse_mode="Markdown")
        else:
            msg = main_bot.send_message(MAIN_LOG_CHAT_ID, final_text, parse_mode="Markdown")
            main_bot.pin_chat_message(MAIN_LOG_CHAT_ID, msg.message_id)
    except Exception as e:
        print(f"[Система] Ошибка сохранения состояния Отца: {e}")

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

    try:
        chat = child_bot.get_chat(bot_config["log_chat_id"])
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == child_bot.get_me().id:
            child_bot.edit_message_text(chat_id=bot_config["log_chat_id"], message_id=pinned_msg.message_id, text=final_text, parse_mode="Markdown")
        else:
            msg = child_bot.send_message(bot_config["log_chat_id"], final_text, parse_mode="Markdown")
            child_bot.pin_chat_message(bot_config["log_chat_id"], msg.message_id)
    except Exception as e:
        print(f"[{token[:5]}] Ошибка обновления личного лог-чата: {e}")

def load_and_start_system():
    """Считывает все настройки при старте Render и поднимает сеть."""
    global system_data
    try:
        chat = main_bot.get_chat(MAIN_LOG_CHAT_ID)
        pinned_msg = chat.pinned_message
        if pinned_msg and pinned_msg.from_user.id == main_bot.get_me().id:
            if "--- СЛУЖЕБНЫЕ ДАННЫЕ ---" in pinned_msg.text:
                json_data = pinned_msg.text.split("--- СЛУЖЕБНЫЕ ДАННЫЕ ---").strip()
                parsed = json.loads(json_data)
                
                system_data["main_templates"] = parsed.get("main_templates", [])
                system_data["bots"] = parsed.get("bots", {})
                
                print(f"[Система] Восстановлено ботов: {len(system_data['bots'])}")
                
                for token in system_data["bots"]:
                    start_child_bot_thread(token)
    except Exception as e:
        print(f"[Система] Ошибка загрузки сети при старте: {e}")


# --- 4. ДВИЖОК ДЛЯ БОТОВ-СЫНОВЕЙ (Для дополнительных каналов) ---
def child_bot_worker(token):
    bot = telebot.TeleBot(token)
    
    @bot.channel_post_handler(content_types=['photo', 'video'])
    def handle_child_channel_post(message):
        bot_config = system_data["bots"].get(token)
        if not bot_config or message.chat.id != bot_config["channel_id"] or not bot_config["templates"]:
            return

        if message.media_group_id:
            if message.media_group_id in processed_albums:
                return
            processed_albums.add(message.media_group_id)
            if len(processed_albums) > 200:
                processed_albums.clear()

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


# --- 5. ЛОГИКА ГЛАВНОГО БОТА (ОТЦА) ДЛЯ ОСНОВНОГО КАНАЛА И СЕТИ ---
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
        "• Команда `/clear` — очистит шапку основного канала.\n\n"
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
    
    print("Центральный мультибот готов к работе!")
    main_bot.infinity_polling(allowed_updates=["message", "channel_post"])


                
        

                    
