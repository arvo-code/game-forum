import sqlite3

import telebot
from telebot import types

TOKEN="8569232372:AAEU3i6gJAPrEmRPJWCk0SQGEPM3Qrr4mJE"
DB = "forum.db"

bot = telebot.TeleBot(TOKEN, parse_mode=None)


# ==================== БАЗА ДАННЫХ ====================
# Правило: открыл (db()) -> запрос -> commit() -> close()

def db():
    return sqlite3.connect(DB)

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            reputation INTEGER NOT NULL DEFAULT 0
        )
    """)
    user_cols = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "reputation" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN reputation INTEGER NOT NULL DEFAULT 0")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author_id INTEGER,
            text TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            author_id INTEGER,
            text TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(tg_id, name):
    conn = db()
    conn.execute(
        """
        INSERT INTO users (tg_id, name, reputation)
        VALUES (?, ?, 0)
        ON CONFLICT(tg_id) DO UPDATE SET name = excluded.name
        """,
        (tg_id, name),
    )
    conn.commit()
    conn.close()


def user_reputation(tg_id):
    conn = db()
    row = conn.execute(
        "SELECT reputation FROM users WHERE tg_id = ?",
        (tg_id,),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def change_reputation(tg_id, delta):
    if tg_id is None:
        return
    conn = db()
    conn.execute(
        "INSERT INTO users (tg_id, name, reputation) VALUES (?, ?, 0) ON CONFLICT(tg_id) DO NOTHING",
        (tg_id, user_name(tg_id) if user_name(tg_id) != "неизвестный" else "Игрок"),
    )
    conn.execute(
        "UPDATE users SET reputation = reputation + ? WHERE tg_id = ?",
        (delta, tg_id),
    )
    conn.commit()
    conn.close()


def leaderboard(limit=10):
    conn = db()
    rows = conn.execute(
        "SELECT tg_id, name, reputation FROM users ORDER BY reputation DESC, name ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows

def add_topic(author_id, title, text):
    conn = db()
    conn.execute(
        "INSERT INTO topics (title, author_id, text) VALUES (?, ?, ?)",
        (title, author_id, text),
    )
    conn.commit()
    conn.close()
    change_reputation(author_id, 5)

def all_topics():
    conn = db()
    rows = conn.execute("""
        SELECT t.id, t.title, u.name
        FROM topics t JOIN users u ON u.tg_id = t.author_id
        ORDER BY t.id DESC
    """).fetchall()
    conn.close()
    return rows

def topic_info(topic_id):
    conn = db()
    row = conn.execute(
        "SELECT title, text FROM topics WHERE id = ?", (topic_id,)
    ).fetchone()
    conn.close()
    return row

def topic_posts(topic_id):
    conn = db()
    rows = conn.execute("""
        SELECT p.text, u.name
        FROM posts p JOIN users u ON u.tg_id = p.author_id
        WHERE p.topic_id = ?
        ORDER BY p.id ASC
    """, (topic_id,)).fetchall()
    conn.close()
    return rows

def add_post(topic_id, author_id, text):
    conn = db()
    conn.execute(
        "INSERT INTO posts (topic_id, author_id, text) VALUES (?, ?, ?)",
        (topic_id, author_id, text),
    )
    conn.commit()
    conn.close()
    change_reputation(author_id, 3)

def add_report(reporter_id, reported_id, reason):
    conn = db()
    conn.execute(
        "INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?)",
        (reporter_id, reported_id, reason),
    )
    conn.commit()
    conn.close()

def all_users():
    conn = db()
    rows = conn.execute("SELECT tg_id, name FROM users").fetchall()
    conn.close()
    return rows

def user_name(tg_id):
    conn = db()
    row = conn.execute(
        "SELECT name FROM users WHERE tg_id = ?", (tg_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else "неизвестный"

init_db()


# ==================== СОСТОЯНИЕ «В ПАМЯТИ» ====================
# waiting хранит, что бот ждёт от конкретного чата:
#   ("topic_text", "Грандис") — создаём тему, ждём текст
#   ("reply", 3)              — отвечаем в теме №3
#   ("report", 101)           — ждём причину жалобы на юзера 101
waiting = {}


# ==================== МЕНЮ ====================
def main_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Все темы", callback_data="topics"),
        types.InlineKeyboardButton("➕ Создать тему", callback_data="newtopic"),
        types.InlineKeyboardButton("🏆 Рейтинг", callback_data="rating"),
        types.InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        types.InlineKeyboardButton("🚨 Пожаловаться", callback_data="reportuser"),
    )
    bot.send_message(
        chat_id,
        "Меню форума. Правила:\n"
        "- Обсуждаем только игры\n"
        "- Без оскорблений\n\n"
        "За темы +5, за ответы +3 репутации.",
        reply_markup=markup,
    )

@bot.message_handler(commands=["main"])
def cmd_main(message):
    waiting.pop(message.chat.id, None)  # сбросить незавершённые действия
    main_menu(message.chat.id)

@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    tg_id = message.from_user.id
    save_user(tg_id, message.from_user.first_name)
    rep = user_reputation(tg_id)
    bot.send_message(
        message.chat.id,
        f"👤 {user_name(tg_id)}\nРепутация: {rep} ⭐",
    )

@bot.message_handler(commands=["rating"])
def cmd_rating(message):
    rows = leaderboard(10)
    if not rows:
        bot.send_message(message.chat.id, "Пока никто не набрал репутацию.")
        return
    lines = ["🏆 Топ игроков:\n"]
    for place, (uid, uname, rep) in enumerate(rows, start=1):
        lines.append(f"{place}. {uname} — {rep} ⭐")
    bot.send_message(message.chat.id, "\n".join(lines))

@bot.message_handler(commands=["start"])
def welcome(message):
    tg_id = message.from_user.id
    name = message.from_user.first_name
    save_user(tg_id, name)
    waiting.pop(message.chat.id, None)
    bot.send_message(
        message.chat.id,
        f"Привет, {name}! Добро пожаловать в игровой форум от @artyom20081.\n\n"
        "Нажми /main, чтобы открыть меню.",
    )
    main_menu(message.chat.id)


# ==================== КНОПКИ ====================
@bot.callback_query_handler(func=lambda call: True)
def on_click(call):
    tg_id = call.from_user.id
    chat_id = call.message.chat.id
    data = call.data

    if data == "topics":
        topics = all_topics()
        if not topics:
            bot.send_message(chat_id, "Тем пока нет. Создай первую! 🎮")
        else:
            lines = ["📋 Все темы:\n"]
            for tid, title, author in topics:
                lines.append(f"#{tid} {title} — {author}")
            lines.append("\nНажми тему, чтобы прочитать:")
            markup = types.InlineKeyboardMarkup(row_width=1)
            for tid, title, _ in topics[:10]:
                markup.add(
                    types.InlineKeyboardButton(
                        f"#{tid} {title}", callback_data=f"open_{tid}"
                    )
                )
            markup.add(
                types.InlineKeyboardButton("◀️ К меню", callback_data="mainmenu")
            )
            bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)

    elif data.startswith("open_"):
        topic_id = int(data.split("_", 1)[1])
        info = topic_info(topic_id)
        if not info:
            bot.send_message(chat_id, "Эта тема была удалена.")
            bot.answer_callback_query(call.id)
            return
        title, text = info
        lines = [f"Тема: {title}\n{text}\n\n— Ответы —\n"]
        posts = topic_posts(topic_id)
        if posts:
            for ptext, author in posts:
                lines.append(f"• {author}: {ptext}")
        else:
            lines.append("Пока без ответов.")
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "✍️ Ответить", callback_data=f"replybtn_{topic_id}"
            ),
            types.InlineKeyboardButton("◀️ К списку", callback_data="topics"),
        )
        bot.send_message(chat_id, "\n".join(lines), reply_markup=markup)
        waiting[chat_id] = ("reply", topic_id)

    elif data == "newtopic":
        save_user(tg_id, user_name(tg_id) if user_name(tg_id) != "неизвестный" else call.from_user.first_name)
        bot.send_message(chat_id, "Введи название темы (одним сообщением):")
        waiting[chat_id] = ("topic_title", None)

    elif data.startswith("replybtn_"):
        topic_id = int(data.split("_", 1)[1])
        bot.send_message(chat_id, f"Введи ответ для темы #{topic_id}:")
        waiting[chat_id] = ("reply", topic_id)

    elif data == "profile":
        save_user(tg_id, call.from_user.first_name)
        bot.send_message(
            chat_id,
            f"👤 {user_name(tg_id)}\nРепутация: {user_reputation(tg_id)} ⭐",
        )

    elif data == "rating":
        rows = leaderboard(10)
        if not rows:
            bot.send_message(chat_id, "Пока никто не набрал репутацию.")
        else:
            lines = ["🏆 Топ игроков:\n"]
            for place, (uid, uname, rep) in enumerate(rows, start=1):
                lines.append(f"{place}. {uname} — {rep} ⭐")
            bot.send_message(chat_id, "\n".join(lines))

    elif data == "reportuser":
        users = all_users()
        if not users:
            bot.send_message(chat_id, "В базе пока нет пользователей для жалобы.")
            bot.answer_callback_query(call.id)
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for uid, uname in users:
            markup.add(
                types.InlineKeyboardButton(
                    f"{uname} ({uid})", callback_data=f"report_{uid}"
                )
            )
        bot.send_message(chat_id, "Выбери, на кого жаловаться:", reply_markup=markup)

    elif data.startswith("report_"):
        target_id = int(data.split("_", 1)[1])
        bot.send_message(
            chat_id,
            f"Жалоба на: {user_name(target_id)}. Введи причину:",
        )
        waiting[chat_id] = ("report", target_id)

    elif data == "mainmenu":
        main_menu(chat_id)

    bot.answer_callback_query(call.id)


# ==================== ТЕКСТОВЫЕ СООБЩЕНИЯ ====================
@bot.message_handler(content_types=["text"])
def on_text(message):
    chat_id = message.chat.id
    tg_id = message.from_user.id
    save_user(tg_id, message.from_user.first_name)
    text = message.text.strip()

    stage, extra = waiting.get(chat_id, (None, None))

    if stage == "topic_title":
        if not text:
            bot.send_message(chat_id, "Название пустое, напиши ещё раз:")
            return
        waiting[chat_id] = ("topic_text", text)
        bot.send_message(chat_id, f'Тема "{text}". Теперь введи текст темы:')

    elif stage == "topic_text":
        title = extra
        if not text:
            bot.send_message(chat_id, "Текст пустой, напиши ещё раз:")
            return
        add_topic(tg_id, title, text)
        waiting.pop(chat_id, None)
        bot.send_message(chat_id, f'Тема "{title}" создана ✅', reply_markup=None)
        bot.send_message(chat_id, "Открой меню, чтобы её увидеть: /main")

    elif stage == "reply":
        topic_id = extra
        if not text:
            bot.send_message(chat_id, "Пустой ответ. Попробуй ещё раз:")
            return
        add_post(topic_id, tg_id, text)
        waiting.pop(chat_id, None)
        bot.send_message(chat_id, f"Ответ в теме #{topic_id} сохранён ✅")

    elif stage == "report":
        target_id = extra
        add_report(tg_id, target_id, text)
        waiting.pop(chat_id, None)
        bot.send_message(chat_id, "Жалоба сохранена, администрация проверит 🙏")

    else:
        bot.send_message(
            chat_id,
            "Я не ждал от тебя текст прямо сейчас.\n"
            "Нажми /main, чтобы открыть меню форума.",
        )


if __name__ == "__main__":
    print("Бот запущен. Ctrl+C чтобы остановить.")
    bot.infinity_polling()

