import asyncio
import sqlite3
import re
import json
import time
from datetime import datetime
from pytz import timezone as tz, UTC
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            mode TEXT DEFAULT 'auto',
            default_text TEXT DEFAULT 'Принял, отвечу позже',
            enabled INTEGER DEFAULT 1,
            timezone TEXT DEFAULT 'UTC',
            media_mode TEXT DEFAULT 'simple',
            schedule_enabled INTEGER DEFAULT 0,
            prefix TEXT DEFAULT '.'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            user_id INTEGER PRIMARY KEY,
            morning_text TEXT,
            day_text TEXT,
            evening_text TEXT,
            night_text TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            condition_type TEXT,
            condition_value TEXT,
            answer TEXT,
            priority INTEGER DEFAULT 5,
            cooldown INTEGER DEFAULT 0,
            last_used TEXT DEFAULT '{}',
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            total_received INTEGER DEFAULT 0,
            total_answered INTEGER DEFAULT 0,
            last_message TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if not user:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        c.execute("INSERT INTO stats (user_id) VALUES (?)", (user_id,))
        c.execute("INSERT INTO schedules (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return get_user(user_id)
    return {
        "user_id": user[0],
        "mode": user[1],
        "default_text": user[2],
        "enabled": bool(user[3]),
        "timezone": user[4],
        "media_mode": user[5],
        "schedule_enabled": bool(user[6]),
        "prefix": user[7]
    }

def update_user(user_id, **kwargs):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    for key, value in kwargs.items():
        c.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def get_schedule(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT morning_text, day_text, evening_text, night_text FROM schedules WHERE user_id = ?", (user_id,))
    schedule = c.fetchone()
    conn.close()
    if schedule:
        return {
            "morning": schedule[0],
            "day": schedule[1],
            "evening": schedule[2],
            "night": schedule[3]
        }
    return {"morning": None, "day": None, "evening": None, "night": None}

def update_schedule(user_id, period, text):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(f"UPDATE schedules SET {period}_text = ? WHERE user_id = ?", (text, user_id))
    conn.commit()
    conn.close()

def add_rule(user_id, name, condition_type, condition_value, answer, priority=5, cooldown=0):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO rules (user_id, name, condition_type, condition_value, answer, priority, cooldown)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, name, condition_type, condition_value, answer, priority, cooldown))
    conn.commit()
    conn.close()

def get_rules(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT * FROM rules WHERE user_id = ? ORDER BY priority ASC", (user_id,))
    rules = c.fetchall()
    conn.close()
    return [{
        "id": r[0],
        "name": r[2],
        "condition_type": r[3],
        "condition_value": r[4],
        "answer": r[5],
        "priority": r[6],
        "cooldown": r[7],
        "last_used": r[8]
    } for r in rules]

def update_rule_condition(rule_id, condition_type, condition_value):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE rules SET condition_type = ?, condition_value = ? WHERE id = ?", (condition_type, condition_value, rule_id))
    conn.commit()
    conn.close()

def update_rule_answer(rule_id, answer):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE rules SET answer = ? WHERE id = ?", (answer, rule_id))
    conn.commit()
    conn.close()

def update_rule_priority(rule_id, priority):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE rules SET priority = ? WHERE id = ?", (priority, rule_id))
    conn.commit()
    conn.close()

def update_rule_cooldown(rule_id, cooldown):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE rules SET cooldown = ? WHERE id = ?", (cooldown, rule_id))
    conn.commit()
    conn.close()

def delete_rule(rule_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()

def update_rule_last_used(rule_id, chat_id, timestamp):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT last_used FROM rules WHERE id = ?", (rule_id,))
    last_used = c.fetchone()[0]
    data = json.loads(last_used) if last_used else {}
    data[str(chat_id)] = timestamp
    c.execute("UPDATE rules SET last_used = ? WHERE id = ?", (json.dumps(data), rule_id))
    conn.commit()
    conn.close()

def update_stats(user_id, received=True, answered=False):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    if received:
        c.execute("UPDATE stats SET total_received = total_received + 1, last_message = ? WHERE user_id = ?", (datetime.now().isoformat(), user_id))
    if answered:
        c.execute("UPDATE stats SET total_answered = total_answered + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_stats(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT total_received, total_answered, last_message FROM stats WHERE user_id = ?", (user_id,))
    stats = c.fetchone()
    conn.close()
    return {"received": stats[0], "answered": stats[1], "last": stats[2]}

def reset_stats(user_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("UPDATE stats SET total_received = 0, total_answered = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_question(text):
    if not text:
        return False
    question_words = ['?', 'кто', 'что', 'где', 'когда', 'почему', 'зачем', 'как', 'сколько', 'какой', 'какая', 'какое', 'какие']
    return '?' in text or any(text.lower().startswith(w) for w in question_words)

def is_urgent(text):
    if not text:
        return False
    urgent_words = ['срочно', 'важно', 'немедленно', 'срочное', 'важное']
    return any(w in text.lower() for w in urgent_words)

def check_cooldown(rule, chat_id):
    data = json.loads(rule["last_used"]) if rule["last_used"] else {}
    last = data.get(str(chat_id), 0)
    return (time.time() - last) > rule["cooldown"] * 60

def get_time_based_response(user_id, user, schedule):
    if not user["schedule_enabled"]:
        return None
    try:
        tz_obj = tz(user["timezone"])
    except:
        tz_obj = UTC
    now = datetime.now(tz_obj)
    hour = now.hour
    
    if 6 <= hour < 12:
        return schedule.get("morning")
    elif 12 <= hour < 18:
        return schedule.get("day")
    elif 18 <= hour < 24:
        return schedule.get("evening")
    else:
        return schedule.get("night")

def check_rule_condition(rule, message, is_question_flag, is_urgent_flag):
    cond_type = rule["condition_type"]
    cond_val = rule["condition_value"]
    text = message.text or ""
    
    if cond_type == "слово":
        return cond_val.lower() in text.lower()
    elif cond_type == "фраза":
        return cond_val.lower() == text.lower()
    elif cond_type == "вопрос":
        return is_question_flag
    elif cond_type == "срочно":
        return is_urgent_flag
    elif cond_type == "медиа фото":
        return bool(message.photo)
    elif cond_type == "медиа голос":
        return bool(message.voice)
    elif cond_type == "медиа видео":
        return bool(message.video)
    elif cond_type == "медиа документ":
        return bool(message.document)
    elif cond_type == "длина больше":
        try:
            return len(text) > int(cond_val)
        except:
            return False
    elif cond_type == "длина меньше":
        try:
            return len(text) < int(cond_val)
        except:
            return False
    return False

async def process_and_reply(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if not user["enabled"]:
        return
    
    update_stats(user_id, received=True)
    
    # Медиа режим simple: ответ по умолчанию на медиа
    if user["media_mode"] == "simple" and (message.photo or message.voice or message.video or message.document):
        media_response = "📎 Медиафайл принят, отвечу позже"
        if message.photo:
            media_response = "📸 Фото принято, спасибо!"
        elif message.voice:
            media_response = "🎤 Голосовое принято, сейчас не могу слушать"
        elif message.video:
            media_response = "🎥 Видео принято, посмотрю позже"
        elif message.document:
            media_response = "📄 Файл принят, отвечу позже"
        await message.reply(media_response)
        update_stats(user_id, answered=True)
        return
    
    # Проверяем правила
    rules = get_rules(user_id)
    is_q = is_question(message.text or "")
    is_u = is_urgent(message.text or "")
    
    # Сортируем правила по приоритету и проверяем
    for rule in sorted(rules, key=lambda x: x["priority"]):
        if check_rule_condition(rule, message, is_q, is_u):
            if rule["cooldown"] > 0 and not check_cooldown(rule, message.chat.id):
                continue
            update_rule_last_used(rule["id"], message.chat.id, time.time())
            await message.reply(rule["answer"])
            update_stats(user_id, answered=True)
            return
    
    # Проверяем расписание
    if user["schedule_enabled"]:
        schedule = get_schedule(user_id)
        schedule_response = get_time_based_response(user_id, user, schedule)
        if schedule_response:
            await message.reply(schedule_response)
            update_stats(user_id, answered=True)
            return
    
    # Базовые режимы
    if user["mode"] == "auto":
        await message.reply(user["default_text"])
        update_stats(user_id, answered=True)
    elif user["mode"] == "smart" and is_q:
        await message.reply(user["default_text"])
        update_stats(user_id, answered=True)
    # silent mode = не отвечаем

@dp.message(F.chat.type == "private")
async def private_messages(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    prefix = user["prefix"]
    text = message.text or ""
    
    # Обработка команд с текущим префиксом
    if text.startswith(prefix):
        await handle_commands(message, prefix)
    elif text.startswith("/") and prefix != "/":
        # Если префикс не /, то / команды не работают (кроме /start для инициализации)
        if text == "/start":
            await handle_commands(message, "/")
        else:
            await message.reply(f"❓ Неизвестная команда. Используйте '{prefix}' перед командами\nПример: {prefix}help")
    elif not text.startswith("/"):
        await message.reply(f"❓ Неизвестная команда. Используйте '{prefix}' перед командами\nПример: {prefix}help")

@dp.message()
async def all_messages(message: types.Message):
    # Сообщение из чата (не из ЛС) - обрабатываем как запрос на ответ
    if message.chat.type != "private":
        await process_and_reply(message)

async def handle_commands(message: types.Message, prefix: str = None):
    user_id = message.from_user.id
    user = get_user(user_id)
    current_prefix = prefix or user["prefix"]
    text = message.text
    # Убираем префикс
    if text.startswith(current_prefix):
        text = text[len(current_prefix):]
    elif text.startswith("/"):
        text = text[1:]
    
    parts = text.split()
    cmd = parts[0].lower() if parts else ""
    args = parts[1:] if len(parts) > 1 else []
    
    # /start
    if cmd == "start":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔘 Включить", callback_data="toggle_on"),
             InlineKeyboardButton(text="🔘 Выключить", callback_data="toggle_off")],
            [InlineKeyboardButton(text="🎮 Режимы", callback_data="menu_modes"),
             InlineKeyboardButton(text="✏️ Мои правила", callback_data="menu_rules")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats"),
             InlineKeyboardButton(text="🕐 Расписание", callback_data="menu_schedule")],
            [InlineKeyboardButton(text="🖼 Медиа", callback_data="menu_media"),
             InlineKeyboardButton(text="📍 Мой пояс", callback_data="menu_timezone")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
             InlineKeyboardButton(text="📖 Полный список", callback_data="menu_full_help")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")]
        ])
        await message.reply(
            "🤖 *Бот-помощник v2.0*\n\nЯ помогаю отвечать в твоих чатах, когда ты занят.\n\n✅ *Как настроить:*\n1. Нажми 📖 Полный список команд\n2. Настрой режим и фразы\n3. Подключи меня в *Настройки → Автоматизация чатов*\n\n⬇️ *Быстрые кнопки:*",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    
    # help
    elif cmd == "help":
        await message.reply(
            f"📚 *Справка*\n\n*Основные команды:*\n{current_prefix}on — включить\n{current_prefix}off — выключить\n{current_prefix}status — текущее состояние\n{current_prefix}set text <текст> — фраза для auto-режима\n\n*Режимы:*\n{current_prefix}mode auto — отвечать всегда\n{current_prefix}mode smart — только на вопросы\n{current_prefix}mode silent — не отвечать\n\n*Расписание:*\n{current_prefix}schedule morning <текст>\n{current_prefix}schedule day <текст>\n{current_prefix}schedule evening <текст>\n{current_prefix}schedule night <текст>\n\n*Правила:*\n{current_prefix}add rule <имя>\n{current_prefix}rule <имя> on слово <слово>\n{current_prefix}rule <имя> answer <текст>\n\n📖 *Полный список:* нажми кнопку в меню",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # on
    elif cmd == "on":
        update_user(user_id, enabled=1)
        await message.reply("✅ Помощник включён")
    
    # off
    elif cmd == "off":
        update_user(user_id, enabled=0)
        await message.reply("❌ Помощник выключен")
    
    # status
    elif cmd == "status":
        rules = get_rules(user_id)
        schedule = get_schedule(user_id)
        await message.reply(
            f"📊 *Статус*\n"
            f"Режим: {user['mode']}\n"
            f"Включён: {'да' if user['enabled'] else 'нет'}\n"
            f"Фраза: {user['default_text']}\n"
            f"Правил: {len(rules)}\n"
            f"Расписание: {'вкл' if user['schedule_enabled'] else 'выкл'}\n"
            f"Медиа: {user['media_mode']}\n"
            f"Префикс: {user['prefix']}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # mode
    elif cmd == "mode" and args:
        mode = args[0]
        if mode in ["auto", "smart", "silent"]:
            update_user(user_id, mode=mode)
            await message.reply(f"🎮 Режим изменён на {mode}")
        else:
            await message.reply("❌ Режим должен быть: auto, smart, silent")
    
    # set text
    elif cmd == "set" and len(args) >= 2 and args[0] == "text":
        new_text = " ".join(args[1:])
        if new_text:
            update_user(user_id, default_text=new_text)
            await message.reply(f"✅ Фраза установлена: {new_text}")
        else:
            await message.reply("❌ Введите текст после set text")
    
    # current text
    elif cmd == "current" and len(args) >= 1 and args[0] == "text":
        await message.reply(f"📝 Текущая фраза: {user['default_text']}")
    
    # add rule
    elif cmd == "add" and len(args) >= 2 and args[0] == "rule":
        name = " ".join(args[1:])
        await message.reply(
            f"✅ Правило '{name}' создано.\n\n"
            f"Теперь настройте его:\n"
            f"{current_prefix}rule {name} on слово <слово>\n"
            f"{current_prefix}rule {name} answer <текст>\n"
            f"{current_prefix}rule {name} priority <1-10>\n"
            f"{current_prefix}rule {name} cooldown <минуты>"
        )
        # Временно сохраняем правило с пустыми полями
        add_rule(user_id, name, "", "", "Ответ не задан", 5, 0)
    
    # rule ... on ...
    elif cmd == "rule" and len(args) >= 4 and args[2] == "on":
        name = args[0]
        cond_type = args[3]
        cond_value = " ".join(args[4:]) if len(args) > 4 else ""
        
        if cond_type not in ["слово", "фраза", "вопрос", "срочно", "медиа", "длина"]:
            await message.reply("❌ Тип условия: слово, фраза, вопрос, срочно, медиа, длина")
            return
        
        rules = get_rules(user_id)
        rule = next((r for r in rules if r["name"] == name), None)
        if rule:
            update_rule_condition(rule["id"], cond_type, cond_value)
            await message.reply(f"✅ Условие для '{name}' обновлено: {cond_type} = {cond_value}")
        else:
            await message.reply(f"❌ Правило '{name}' не найдено")
    
    # rule ... answer ...
    elif cmd == "rule" and len(args) >= 3 and args[2] == "answer":
        name = args[0]
        answer = " ".join(args[3:])
        rules = get_rules(user_id)
        rule = next((r for r in rules if r["name"] == name), None)
        if rule:
            update_rule_answer(rule["id"], answer)
            await message.reply(f"✅ Ответ для '{name}' установлен: {answer}")
        else:
            await message.reply(f"❌ Правило '{name}' не найдено")
    
    # rule ... priority ...
    elif cmd == "rule" and len(args) >= 3 and args[2] == "priority":
        name = args[0]
        try:
            priority = int(args[3])
            if 1 <= priority <= 10:
                rules = get_rules(user_id)
                rule = next((r for r in rules if r["name"] == name), None)
                if rule:
                    update_rule_priority(rule["id"], priority)
                    await message.reply(f"✅ Приоритет для '{name}' установлен: {priority}")
                else:
                    await message.reply(f"❌ Правило '{name}' не найдено")
            else:
                await message.reply("❌ Приоритет должен быть от 1 до 10")
        except:
            await message.reply("❌ Использование: rule <имя> priority <число>")
    
    # rule ... cooldown ...
    elif cmd == "rule" and len(args) >= 3 and args[2] == "cooldown":
        name = args[0]
        try:
            cooldown = int(args[3])
            rules = get_rules(user_id)
            rule = next((r for r in rules if r["name"] == name), None)
            if rule:
                update_rule_cooldown(rule["id"], cooldown)
                await message.reply(f"✅ Cooldown для '{name}' установлен: {cooldown} мин")
            else:
                await message.reply(f"❌ Правило '{name}' не найдено")
        except:
            await message.reply("❌ Использование: rule <имя> cooldown <минуты>")
    
    # list rules
    elif cmd == "list" and len(args) >= 1 and args[0] == "rules":
        rules = get_rules(user_id)
        if not rules:
            await message.reply("📭 У вас нет правил")
        else:
            msg = "📋 *Ваши правила:*\n\n"
            for r in rules:
                msg += f"• *{r['name']}*: {r['condition_type']}='{r['condition_value']}' → {r['answer'][:40]}...\n  Приор:{r['priority']} | Cooldown:{r['cooldown']}мин\n"
            await message.reply(msg, parse_mode=ParseMode.MARKDOWN)
    
    # remove rule
    elif cmd == "remove" and len(args) >= 2 and args[0] == "rule":
        name = " ".join(args[1:])
        rules = get_rules(user_id)
        rule = next((r for r in rules if r["name"] == name), None)
        if rule:
            delete_rule(rule["id"])
            await message.reply(f"✅ Правило '{name}' удалено")
        else:
            await message.reply(f"❌ Правило '{name}' не найдено")
    
    # schedule
    elif cmd == "schedule":
        if len(args) == 0:
            await message.reply(
                f"📅 *Управление расписанием*\n\n"
                f"{current_prefix}schedule morning <текст>\n"
                f"{current_prefix}schedule day <текст>\n"
                f"{current_prefix}schedule evening <текст>\n"
                f"{current_prefix}schedule night <текст>\n"
                f"{current_prefix}schedule list\n"
                f"{current_prefix}schedule on\n"
                f"{current_prefix}schedule off",
                parse_mode=ParseMode.MARKDOWN
            )
        elif args[0] in ["morning", "day", "evening", "night"] and len(args) >= 2:
            period = args[0]
            text_response = " ".join(args[1:])
            update_schedule(user_id, period, text_response)
            await message.reply(f"✅ Фраза для {period} установлена")
        elif args[0] == "list":
            schedule = get_schedule(user_id)
            await message.reply(
                f"📅 *Текущее расписание*\n\n"
                f"🌅 Утро (6-12): {schedule['morning'] or 'не задано'}\n"
                f"☀️ День (12-18): {schedule['day'] or 'не задано'}\n"
                f"🌙 Вечер (18-24): {schedule['evening'] or 'не задано'}\n"
                f"🌃 Ночь (0-6): {schedule['night'] or 'не задано'}",
                parse_mode=ParseMode.MARKDOWN
            )
        elif args[0] == "on":
            update_user(user_id, schedule_enabled=1)
            await message.reply("✅ Расписание включено")
        elif args[0] == "off":
            update_user(user_id, schedule_enabled=0)
            await message.reply("❌ Расписание выключено")
    
    # timezone
    elif cmd == "timezone":
        if len(args) == 0:
            await message.reply(f"📍 Текущий часовой пояс: {user['timezone']}\n\nИспользование: {current_prefix}timezone +3\nИли {current_prefix}timezone Europe/Moscow")
        else:
            new_tz = args[0]
            try:
                # Проверяем, что часовой пояс существует
                tz(new_tz)
                update_user(user_id, timezone=new_tz)
                await message.reply(f"✅ Часовой пояс установлен: {new_tz}")
            except:
                await message.reply("❌ Неверный часовой пояс. Примеры: +3, Europe/Moscow, Asia/Yekaterinburg")
    
    # media
    elif cmd == "media":
        if len(args) == 0:
            await message.reply(
                f"🖼 *Медиа режим*\n\nТекущий: {user['media_mode']}\n\n"
                f"{current_prefix}media simple — отвечать стандартной фразой\n"
                f"{current_prefix}media off — не отвечать на медиа",
                parse_mode=ParseMode.MARKDOWN
            )
        elif args[0] in ["simple", "off"]:
            update_user(user_id, media_mode=args[0])
            await message.reply(f"✅ Медиа режим изменён на {args[0]}")
    
    # prefix
    elif cmd == "prefix":
        if len(args) == 0:
            await message.reply(f"⚙️ Текущий префикс: {user['prefix']}\n\nИспользование: {current_prefix}prefix .\nИли {current_prefix}prefix /")
        else:
            new_prefix = args[0]
            if new_prefix in [".", "/"]:
                update_user(user_id, prefix=new_prefix)
                await message.reply(f"✅ Префикс команд изменён на {new_prefix}\n\nТеперь используйте {new_prefix}help для справки")
            else:
                await message.reply("❌ Префикс должен быть . или /")
    
    # stats
    elif cmd == "stats":
        stats = get_stats(user_id)
        rules = get_rules(user_id)
        await message.reply(
            f"📊 *Статистика*\n\n"
            f"📥 Получено сообщений: {stats['received']}\n"
            f"📤 Отвечено: {stats['answered']}\n"
            f"📋 Всего правил: {len(rules)}\n"
            f"🕐 Последнее сообщение: {stats['last'] or 'нет'}",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # reset
    elif cmd == "reset":
        reset_stats(user_id)
        await message.reply("✅ Статистика сброшена")
    
    # test
    elif cmd == "test" and len(args) >= 1:
        test_msg = " ".join(args)
        fake_message = types.Message(message_id=0, from_user=message.from_user, chat=message.chat, date=datetime.now(), text=test_msg)
        rules = get_rules(user_id)
        is_q = is_question(test_msg)
        is_u = is_urgent(test_msg)
        
        matched = None
        for rule in sorted(rules, key=lambda x: x["priority"]):
            if check_rule_condition(rule, fake_message, is_q, is_u):
                matched = rule
                break
        
        if matched:
            await message.reply(
                f"🧪 *Тест*\n\n"
                f"Сообщение: {test_msg}\n\n"
                f"✅ Правило '{matched['name']}'\n"
                f"Ответ: {matched['answer']}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.reply(
                f"🧪 *Тест*\n\n"
                f"Сообщение: {test_msg}\n\n"
                f"❌ Ни одно правило не подошло\n"
                f"Базовый режим: {user['mode']}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    # guide
    elif cmd == "guide":
        await message.reply(
            "📌 *Как подключить бота в чаты:*\n\n"
            "1. Открой Настройки Telegram\n"
            "2. Найди раздел «Автоматизация чатов»\n"
            "3. Нажми «Подключить бота»\n"
            "4. Введи моё имя @your_bot_username\n"
            "5. Выбери «Все чаты, кроме...» или «Только выбранные»\n"
            "6. Отметь нужные чаты или исключения\n\n"
            "После этого я буду отвечать в выбранных чатах!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    else:
        await message.reply(f"❌ Неизвестная команда. Напишите {current_prefix}help")

@dp.callback_query()
async def handle_callbacks(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    prefix = user["prefix"]
    data = callback.data
    
    if data == "toggle_on":
        update_user(user_id, enabled=1)
        await callback.message.edit_text("✅ Помощник включён")
    elif data == "toggle_off":
        update_user(user_id, enabled=0)
        await callback.message.edit_text("❌ Помощник выключен")
    
    elif data == "menu_modes":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 Auto", callback_data="mode_auto"),
             InlineKeyboardButton(text="🧠 Smart", callback_data="mode_smart"),
             InlineKeyboardButton(text="🤫 Silent", callback_data="mode_silent")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
        ])
        await callback.message.edit_text("🎮 *Выберите режим:*", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "mode_auto":
        update_user(user_id, mode="auto")
        await callback.message.edit_text("✅ Режим: Auto (отвечать всегда)")
    elif data == "mode_smart":
        update_user(user_id, mode="smart")
        await callback.message.edit_text("✅ Режим: Smart (только на вопросы)")
    elif data == "mode_silent":
        update_user(user_id, mode="silent")
        await callback.message.edit_text("✅ Режим: Silent (не отвечать)")
    
    elif data == "menu_settings":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Сменить префикс", callback_data="settings_prefix")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
        ])
        await callback.message.edit_text("⚙️ *Настройки*\n\nВыберите опцию:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "settings_prefix":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔘 . (точка)", callback_data="prefix_dot"),
             InlineKeyboardButton(text="🔘 / (слеш)", callback_data="prefix_slash")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_settings")]
        ])
        await callback.message.edit_text(f"⚙️ *Смена префикса*\n\nТекущий: {user['prefix']}\n\nВыберите новый:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "prefix_dot":
        update_user(user_id, prefix=".")
        await callback.message.edit_text("✅ Префикс изменён на .\n\nТеперь используйте .help для команд")
    elif data == "prefix_slash":
        update_user(user_id, prefix="/")
        await callback.message.edit_text("✅ Префикс изменён на /\n\nТеперь используйте /help для команд")
    
    elif data == "menu_rules":
        rules = get_rules(user_id)
        if not rules:
            await callback.message.edit_text("📭 У вас нет правил\n\nСоздайте: .add rule <имя>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]]))
        else:
            msg = "📋 *Ваши правила:*\n\n"
            for r in rules[:5]:
                msg += f"• {r['name']}: {r['condition_type']} → {r['answer'][:30]}...\n"
            msg += f"\nВсего: {len(rules)} правил\n\nКоманда: {prefix}list rules"
            await callback.message.edit_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]]))
    
    elif data == "menu_stats":
        stats = get_stats(user_id)
        await callback.message.edit_text(f"📊 *Статистика*\n\nПолучено: {stats['received']}\nОтвечено: {stats['answered']}\nПоследнее: {stats['last'] or 'нет'}", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]]))
    
    elif data == "menu_schedule":
        schedule = get_schedule(user_id)
        await callback.message.edit_text(
            f"📅 *Расписание*\n\n"
            f"Статус: {'включено' if user['schedule_enabled'] else 'выключено'}\n"
            f"Утро: {schedule['morning'] or 'не задано'}\n"
            f"День: {schedule['day'] or 'не задано'}\n"
            f"Вечер: {schedule['evening'] or 'не задано'}\n"
            f"Ночь: {schedule['night'] or 'не задано'}\n\n"
            f"Команда: {prefix}schedule on/off",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🕐 Вкл", callback_data="schedule_on"),
                 InlineKeyboardButton(text="🕐 Выкл", callback_data="schedule_off")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
            ])
        )
    
    elif data == "schedule_on":
        update_user(user_id, schedule_enabled=1)
        await callback.message.edit_text("✅ Расписание включено")
    elif data == "schedule_off":
        update_user(user_id, schedule_enabled=0)
        await callback.message.edit_text("❌ Расписание выключено")
    
    elif data == "menu_media":
        await callback.message.edit_text(
            f"🖼 *Медиа режим*\n\n"
            f"Текущий: {user['media_mode']}\n\n"
            f"simple — отвечать стандартной фразой\n"
            f"off — не отвечать на медиа\n\n"
            f"Команда: {prefix}media simple/off",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🖼 Simple", callback_data="media_simple"),
                 InlineKeyboardButton(text="🚫 Off", callback_data="media_off")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
            ])
        )
    
    elif data == "media_simple":
        update_user(user_id, media_mode="simple")
        await callback.message.edit_text("✅ Медиа режим: Simple")
    elif data == "media_off":
        update_user(user_id, media_mode="off")
        await callback.message.edit_text("✅ Медиа режим: Off")
    
    elif data == "menu_timezone":
        await callback.message.edit_text(
            f"📍 *Часовой пояс*\n\nТекущий: {user['timezone']}\n\n"
            f"Установите командой:\n{prefix}timezone +3\n"
            f"Или {prefix}timezone Europe/Moscow",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]])
        )
    
    elif data == "menu_help":
        await callback.message.edit_text(
            f"📚 *Справка*\n\n"
            f"{prefix}on — включить\n"
            f"{prefix}off — выключить\n"
            f"{prefix}status — статус\n"
            f"{prefix}mode auto/smart/silent\n"
            f"{prefix}set text <текст>\n"
            f"{prefix}add rule <имя>\n"
            f"{prefix}list rules\n\n"
            f"📖 Полный список — в главном меню",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]])
        )
    
    elif data == "menu_full_help":
        await callback.message.edit_text(
            f"📖 *ПОЛНЫЙ СПИСОК КОМАНД*\n\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 *ОСНОВНЫЕ*\n"
            f"{prefix}on — включить\n"
            f"{prefix}off — выключить\n"
            f"{prefix}status — текущий статус\n"
            f"{prefix}guide — как подключить\n\n"
            f"🔹 *РЕЖИМЫ*\n"
            f"{prefix}mode auto — отвечать всегда\n"
            f"{prefix}mode smart — только на вопросы\n"
            f"{prefix}mode silent — не отвечать\n\n"
            f"🔹 *НАСТРОЙКА*\n"
            f"{prefix}set text <текст> — фраза для auto\n"
            f"{prefix}current text — показать фразу\n"
            f"{prefix}prefix . или / — сменить префикс\n\n"
            f"🔹 *РАСПИСАНИЕ*\n"
            f"{prefix}timezone +3 — установить пояс\n"
            f"{prefix}schedule morning <текст>\n"
            f"{prefix}schedule day <текст>\n"
            f"{prefix}schedule evening <текст>\n"
            f"{prefix}schedule night <текст>\n"
            f"{prefix}schedule on/off\n\n"
            f"🔹 *ПРАВИЛА*\n"
            f"{prefix}add rule <имя> — создать\n"
            f"{prefix}rule <имя> on слово <слово>\n"
            f"{prefix}rule <имя> on вопрос\n"
            f"{prefix}rule <имя> on срочно\n"
            f"{prefix}rule <имя> on медиа фото\n"
            f"{prefix}rule <имя> answer <текст>\n"
            f"{prefix}rule <имя> priority <1-10>\n"
            f"{prefix}rule <имя> cooldown <мин>\n"
            f"{prefix}list rules — показать\n"
            f"{prefix}remove rule <имя> — удалить\n\n"
            f"🔹 *СТАТИСТИКА*\n"
            f"{prefix}stats — статистика\n"
            f"{prefix}reset — сбросить\n"
            f"{prefix}test <сообщение> — тест\n\n"
            f"🔹 *МЕДИА*\n"
            f"{prefix}media simple — отвечать на медиа\n"
            f"{prefix}media off — игнорировать\n\n"
            f"💡 *Пример правила:*\n"
            f"{prefix}add rule клиент\n"
            f"{prefix}rule клиент on слово цена\n"
            f"{prefix}rule клиент answer Напишите телефон\n"
            f"{prefix}rule клиент priority 1",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]])
        )
    
    elif data == "back_main":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔘 Включить", callback_data="toggle_on"),
             InlineKeyboardButton(text="🔘 Выключить", callback_data="toggle_off")],
            [InlineKeyboardButton(text="🎮 Режимы", callback_data="menu_modes"),
             InlineKeyboardButton(text="✏️ Мои правила", callback_data="menu_rules")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats"),
             InlineKeyboardButton(text="🕐 Расписание", callback_data="menu_schedule")],
            [InlineKeyboardButton(text="🖼 Медиа", callback_data="menu_media"),
             InlineKeyboardButton(text="📍 Мой пояс", callback_data="menu_timezone")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
             InlineKeyboardButton(text="📖 Полный список", callback_data="menu_full_help")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")]
        ])
        await callback.message.edit_text("🤖 *Бот-помощник v2.0*\n\nВыберите действие:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    
    await callback.answer()

async def main():
    print("🚀 Бот-помощник запущен...")
    print("Поддерживаемые команды:")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())