import os
import sqlite3
import logging
import random
import asyncio
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand,
    ReactionTypeEmoji
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatMemberHandler, ContextTypes, filters
)

# ============================================================
#                    CONFIG SECTION
#         (Edit these values directly in the code)
# ============================================================

CONFIG = {
    # --- Bot Token (from @BotFather) ---
    "BOT_TOKEN": "8830876990:AAEBeYX8_AZrTWQLvYQUxXSJRn2T_XmKbHQ",

    # --- Owner's Telegram User ID ---
    "OWNER_ID": 8264584451,

    # --- Database file ---
    "DB_FILE": "bot_data.db",

    # ==================== BRANDING ====================
    "BOT_NAME": "Fixo Dev Bot",
    "COPYRIGHT": "© Fixo Dev",
    "BRANDING": "🤖 Powered by *Fixo Dev*",

    # ==================== DEFAULT WELCOME ====================
    "DEFAULT_WELCOME_TEXT": (
        "🎉 *Welcome, {name}!*\n\n"
        "Thank you for joining *{chat_title}*! 🙏\n\n"
        "👥 Members: {member_count}\n"
        "🕐 Time: {time}\n\n"
        "Stay tuned for more updates! 💙"
    ),

    "DEFAULT_WELCOME_PHOTO": "https://files.catbox.moe/59239f.png",
    "DEFAULT_WELCOME_VIDEO": "https://files.catbox.moe/gb1uf8.mp4",

    # ==================== AUTO REACTIONS ====================
    "DEFAULT_AUTO_REACT": 1,

    "REACTION_EMOJIS": [
        "👍", "❤️", "🔥", "🎉", "👏", "💯",
        "😍", "🤩", "⚡", "💎", "🚀", "✨",
        "🙏", "👌", "💪", "🌟"
    ],

    "REACT_DELAY_MIN": 1,
    "REACT_DELAY_MAX": 4,

    "MAX_TEXT_LENGTH": 1000,
}

# ============================================================
#                    DATABASE
# ============================================================

def init_db():
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            chat_id      INTEGER PRIMARY KEY,
            title        TEXT,
            welcome_text TEXT,
            photo_url    TEXT,
            video_url    TEXT,
            enabled      INTEGER DEFAULT 1,
            auto_react   INTEGER DEFAULT 1,
            added_by     INTEGER,
            added_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    try:
        c.execute("ALTER TABLE channels ADD COLUMN auto_react INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            first_name TEXT,
            joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS welcome_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            user_id     INTEGER,
            welcomed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reaction_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            message_id  INTEGER,
            emoji       TEXT,
            reacted_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def get_channel(chat_id):
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE chat_id = ?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row


def save_channel(chat_id, title, welcome_text=None, photo_url=None,
                 video_url=None, added_by=None):
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("""
        INSERT INTO channels (chat_id, title, welcome_text, photo_url, video_url, added_by)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            title = excluded.title,
            welcome_text = COALESCE(excluded.welcome_text, channels.welcome_text),
            photo_url = COALESCE(excluded.photo_url, channels.photo_url),
            video_url = COALESCE(excluded.video_url, channels.video_url)
    """, (
        chat_id, title,
        welcome_text or CONFIG["DEFAULT_WELCOME_TEXT"],
        photo_url if photo_url is not None else CONFIG["DEFAULT_WELCOME_PHOTO"],
        video_url if video_url is not None else CONFIG["DEFAULT_WELCOME_VIDEO"],
        added_by
    ))
    conn.commit()
    conn.close()


def update_channel_field(chat_id, field, value):
    allowed = ["welcome_text", "photo_url", "video_url", "enabled", "auto_react"]
    if field not in allowed:
        return False
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute(f"UPDATE channels SET {field} = ? WHERE chat_id = ?", (value, chat_id))
    conn.commit()
    conn.close()
    return True


def get_all_channels():
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("SELECT chat_id, title FROM channels WHERE enabled = 1")
    rows = c.fetchall()
    conn.close()
    return rows


def log_welcome(chat_id, user_id):
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("INSERT INTO welcome_log (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
    conn.commit()
    conn.close()


def log_reaction(chat_id, message_id, emoji):
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute(
        "INSERT INTO reaction_log (chat_id, message_id, emoji) VALUES (?, ?, ?)",
        (chat_id, message_id, emoji)
    )
    conn.commit()
    conn.close()


def count_reactions(chat_id):
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM reaction_log WHERE chat_id = ?", (chat_id,))
    n = c.fetchone()[0]
    conn.close()
    return n


def save_user(user):
    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
    """, (user.id, user.username, user.first_name))
    conn.commit()
    conn.close()


# ============================================================
#                    HELPERS
# ============================================================

def is_owner(user_id):
    return CONFIG["OWNER_ID"] != 0 and user_id == CONFIG["OWNER_ID"]


def with_branding(text: str) -> str:
    return f"{text}\n\n━━━━━━━━━━━━━━━\n{CONFIG['BRANDING']}\n{CONFIG['COPYRIGHT']}"


def build_welcome_text(template, user, chat, member_count):
    return template.format(
        name=user.first_name or user.username or "Friend",
        chat_title=chat.title or "Channel",
        member_count=member_count,
        time=datetime.now().strftime("%Y-%m-%d %H:%M")
    )


# ============================================================
#                    WELCOME HANDLER
# ============================================================

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    joined = (
        old_status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]
        and new_status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER
        ]
    )
    if not joined:
        return

    user = result.new_chat_member.user
    chat = result.chat

    if user.is_bot:
        return

    channel = get_channel(chat.id)
    if not channel:
        save_channel(chat.id, chat.title, added_by=None)
        channel = get_channel(chat.id)

    if channel and channel[5] == 0:
        return

    welcome_text = channel[2] if channel and channel[2] else CONFIG["DEFAULT_WELCOME_TEXT"]
    photo_url = channel[3] if channel and channel[3] else CONFIG["DEFAULT_WELCOME_PHOTO"]
    video_url = channel[4] if channel and channel[4] else CONFIG["DEFAULT_WELCOME_VIDEO"]

    try:
        member_count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        member_count = "N/A"

    text = build_welcome_text(welcome_text, user, chat, member_count)
    text = with_branding(text)

    try:
        if video_url:
            await context.bot.send_video(
                chat_id=chat.id,
                video=video_url,
                caption=text,
                parse_mode=ParseMode.MARKDOWN
            )
        elif photo_url:
            await context.bot.send_photo(
                chat_id=chat.id,
                photo=photo_url,
                caption=text,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=chat.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )

        log_welcome(chat.id, user.id)

    except Exception as e:
        logger.error(f"Welcome error in {chat.id}: {e}")


# ============================================================
#                    AUTO REACTION HANDLER
# ============================================================

async def auto_react_to_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post or update.effective_message
    if not message:
        return

    chat_id = message.chat_id

    channel = get_channel(chat_id)
    if not channel:
        save_channel(chat_id, message.chat.title, added_by=None)
        channel = get_channel(chat_id)

    if channel and len(channel) > 6 and channel[6] == 0:
        return

    delay = random.uniform(CONFIG["REACT_DELAY_MIN"], CONFIG["REACT_DELAY_MAX"])
    await asyncio.sleep(delay)

    emoji = random.choice(CONFIG["REACTION_EMOJIS"])

    try:
        await context.bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)]
        )
        log_reaction(chat_id, message.message_id, emoji)
        logger.info(f"✅ Reacted {emoji} to message {message.message_id} in {chat_id}")
    except Exception as e:
        logger.error(f"Reaction error in {chat_id}: {e}")


# ============================================================
#                    MAIN COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)

    text = (
        f"👋 *Hello {user.first_name}!*\n\n"
        f"Welcome to *{CONFIG['BOT_NAME']}*!\n"
        f"Your ID: `{user.id}`\n\n"
        "📌 *Main Commands:*\n"
        "• /start — Show this menu\n"
        "• /help — How to use me\n"
        "• /about — About this bot\n\n"
        "🆔 *Chat ID Commands:*\n"
        "• /id — Your User ID + Chat ID\n"
        "• /chatid — Current chat ID\n"
        "• /userid — Your User ID only\n"
        "• /channelid — Forward a message to get channel ID\n\n"
        "📊 *Channel Commands:*\n"
        "• /stats — Channel statistics\n"
        "• /setup — Configure welcome\n"
        "• /mywelcome — View current welcome\n"
        "• /settext — Set welcome text\n"
        "• /setphoto — Set welcome photo\n"
        "• /setvideo — Set welcome video\n"
        "• /toggle — Enable/disable welcome\n"
        "• /react — Toggle auto-reactions\n"
        "• /remove — Remove channel config\n\n"
        "➕ *Get Started:*\n"
        "1. Add me to your channel as admin\n"
        "2. I'll send welcomes + auto-react to posts! 🎯"
    )

    keyboard = [
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("🆔 Chat ID", callback_data="chatid")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("ℹ️ About", callback_data="about")],
        [InlineKeyboardButton("⚙️ Setup Guide", callback_data="setup")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        with_branding(text),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 *How to Use Me*\n\n"
        "*Step 1:* Add me to your Telegram channel\n"
        "*Step 2:* Make me an *Administrator*:\n"
        "   ✅ Post Messages\n"
        "   ✅ Delete Messages\n"
        "   ✅ Invite Users\n\n"
        "*Step 3:* I'll auto-send welcome messages!\n"
        "*Step 4:* I'll auto-react to every post! 🎯\n\n"
        "🆔 *Get Chat IDs:*\n"
        "• `/id` — All your IDs\n"
        "• `/chatid` — Current chat ID\n"
        "• `/userid` — Your user ID\n"
        "• `/channelid` — Forward a msg from any channel\n\n"
        "🎨 *Customize Welcome:*\n"
        "• `/settext Your text`\n"
        "• `/setphoto <url>`\n"
        "• `/setvideo <url>`\n"
        "• `/mywelcome`\n"
        "• `/toggle` — On/off\n"
        "• `/react` — Toggle auto-reactions\n\n"
        "📝 *Placeholders:*\n"
        "`{name}`, `{chat_title}`, `{member_count}`, `{time}`"
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"ℹ️ *About {CONFIG['BOT_NAME']}*\n\n"
        f"🤖 A powerful public Telegram bot for channel management.\n\n"
        f"*Features:*\n"
        f"• Auto welcome messages\n"
        f"• Custom photo/video welcomes\n"
        f"• Auto-reactions with random emojis\n"
        f"• Chat ID lookup tools\n"
        f"• Channel statistics\n"
        f"• Multi-channel support\n"
        f"• 100% free to use\n\n"
        f"👨‍💻 *Developer:* Fixo Dev\n"
        f"📅 *Version:* 2.5\n\n"
        f"{CONFIG['COPYRIGHT']}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ============================================================
#                    CHAT ID COMMANDS
# ============================================================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/id - Show both user ID and chat ID"""
    user = update.effective_user
    chat = update.effective_chat
    save_user(user)

    text = (
        f"🆔 *Your IDs*\n\n"
        f"👤 *User ID:* `{user.id}`\n"
        f"📛 *Name:* {user.first_name or 'N/A'}\n"
        f"🔗 *Username:* @{user.username or 'N/A'}\n\n"
        f"💬 *Chat ID:* `{chat.id}`\n"
        f"📌 *Chat Type:* `{chat.type}`\n"
        f"📛 *Chat Title:* {chat.title or 'Private'}\n\n"
        f"💡 Copy the ID to use in your bot config."
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/chatid - Show current chat ID"""
    chat = update.effective_chat

    text = (
        f"💬 *Current Chat Info*\n\n"
        f"🆔 *Chat ID:* `{chat.id}`\n"
        f"📌 *Type:* `{chat.type}`\n"
        f"📛 *Title:* {chat.title or 'Private Chat'}\n"
        f"🔗 *Username:* @{chat.username or 'N/A'}\n\n"
        f"💡 *Use this ID in your config or bots.*"
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


async def userid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/userid - Show user ID only"""
    user = update.effective_user
    save_user(user)

    text = (
        f"👤 *Your User ID*\n\n"
        f"🆔 `{user.id}`\n\n"
        f"📛 *Name:* {user.first_name or 'N/A'}\n"
        f"🔗 *Username:* @{user.username or 'N/A'}\n"
        f"🌐 *Language:* {user.language_code or 'N/A'}\n"
        f"🤖 *Is Bot:* {user.is_bot}"
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


async def channelid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/channelid - Forward a message from any channel to get its ID"""
    # If command has a forwarded message attached
    if update.message and update.message.reply_to_message:
        forwarded = update.message.reply_to_message
        origin = forwarded.forward_origin

        if origin:
            # Channel forward
            if hasattr(origin, "chat") and origin.chat:
                text = (
                    f"📢 *Forwarded Channel Info*\n\n"
                    f"🆔 *Channel ID:* `{origin.chat.id}`\n"
                    f"📛 *Title:* {origin.chat.title}\n"
                    f"🔗 *Username:* @{origin.chat.username or 'N/A'}\n"
                    f"📌 *Type:* `{origin.chat.type}`"
                )
                await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)
                return

            # User forward
            if hasattr(origin, "sender_user") and origin.sender_user:
                u = origin.sender_user
                text = (
                    f"👤 *Forwarded User Info*\n\n"
                    f"🆔 *User ID:* `{u.id}`\n"
                    f"📛 *Name:* {u.first_name}\n"
                    f"🔗 *Username:* @{u.username or 'N/A'}"
                )
                await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)
                return

    # No forwarded message - show instructions
    text = (
        "📢 *Channel ID Lookup*\n\n"
        "*How to get any channel's ID:*\n\n"
        "1️⃣ Open the channel you want\n"
        "2️⃣ Forward any message from it to me\n"
        "3️⃣ Reply to that forwarded message with `/channelid`\n\n"
        "*Or simply:*\n"
        "• Add me to the channel as admin\n"
        "• Send `/chatid` inside the channel\n\n"
        "💡 *Tip:* For private channels, forwarding is the easiest way!"
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


# ============================================================
#                    CHANNEL COMMANDS
# ============================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text(
            "❌ *Please use this command inside a channel or group.*",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        member_count = await context.bot.get_chat_member_count(chat.id)
        chat_info = await context.bot.get_chat(chat.id)

        try:
            admins = await context.bot.get_chat_administrators(chat.id)
            admin_count = len(admins)
        except Exception:
            admin_count = "N/A"

        conn = sqlite3.connect(CONFIG["DB_FILE"])
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM welcome_log WHERE chat_id = ?", (chat.id,))
        total_welcomes = c.fetchone()[0]
        conn.close()

        total_reactions = count_reactions(chat.id)

        channel = get_channel(chat.id)
        enabled = "✅ ON" if (channel and channel[5] == 1) else "❌ OFF"
        react_status = "✅ ON" if (channel and len(channel) > 6 and channel[6] == 1) else "❌ OFF"

        text = (
            f"📊 *Channel Statistics*\n\n"
            f"📛 *Name:* {chat_info.title}\n"
            f"🆔 *Chat ID:* `{chat.id}`\n"
            f"👥 *Members:* {member_count}\n"
            f"👑 *Admins:* {admin_count}\n"
            f"🔗 *Type:* {chat_info.type}\n"
            f"🎉 *Total Welcomes:* {total_welcomes}\n"
            f"❤️ *Total Reactions:* {total_reactions}\n"
            f"⚙️ *Welcome:* {enabled}\n"
            f"💫 *Reactions:* {react_status}\n"
            f"🕐 *Checked:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚙️ *Setup Guide*\n\n"
        "*To configure welcome messages:*\n\n"
        "1️⃣ Add me to your channel as *Administrator*\n"
        "2️⃣ Send these commands *inside the channel*:\n\n"
        "📝 `/settext Welcome {name}! Thanks for joining {chat_title}.`\n"
        "🖼️ `/setphoto https://example.com/welcome.jpg`\n"
        "🎬 `/setvideo https://example.com/welcome.mp4`\n"
        "👀 `/mywelcome` — View settings\n"
        "🔛 `/toggle` — Enable/disable welcome\n"
        "❤️ `/react` — Enable/disable reactions\n"
        "🗑️ `/remove` — Reset\n\n"
        "*Placeholders:*\n"
        "`{name}`, `{chat_title}`, `{member_count}`, `{time}`"
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


async def mywelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    channel = get_channel(chat.id)
    if not channel:
        save_channel(chat.id, chat.title, added_by=update.effective_user.id)
        channel = get_channel(chat.id)

    react_state = "✅ ON" if (len(channel) > 6 and channel[6] == 1) else "❌ OFF"

    text = (
        f"📋 *Current Welcome Settings*\n\n"
        f"📛 *Channel:* {channel[1]}\n"
        f"⚙️ *Welcome:* {'✅ ON' if channel[5] == 1 else '❌ OFF'}\n"
        f"💫 *Auto-Reactions:* {react_state}\n\n"
        f"📝 *Text:*\n{channel[2] or 'Not set'}\n\n"
        f"🖼️ *Photo:* {channel[3] or 'Not set'}\n"
        f"🎬 *Video:* {channel[4] or 'Not set'}"
    )
    await update.message.reply_text(with_branding(text), parse_mode=ParseMode.MARKDOWN)


async def settext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    if not context.args:
        await update.message.reply_text(
            "📝 *Usage:* `/settext Your message`\n\n"
            "Placeholders: `{name}`, `{chat_title}`, `{member_count}`, `{time}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    new_text = " ".join(context.args)
    if len(new_text) > CONFIG["MAX_TEXT_LENGTH"]:
        await update.message.reply_text(f"❌ Max {CONFIG['MAX_TEXT_LENGTH']} chars.")
        return

    if not get_channel(chat.id):
        save_channel(chat.id, chat.title, added_by=update.effective_user.id)

    update_channel_field(chat.id, "welcome_text", new_text)

    await update.message.reply_text(
        with_branding(
            f"✅ *Welcome text updated!*\n\n"
            f"Preview:\n{build_welcome_text(new_text, update.effective_user, chat, 'N/A')}"
        ),
        parse_mode=ParseMode.MARKDOWN
    )


async def setphoto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    if not context.args:
        await update.message.reply_text("🖼️ *Usage:* `/setphoto <image_url>`", parse_mode=ParseMode.MARKDOWN)
        return

    url = context.args[0]
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("❌ Provide a valid URL.")
        return

    if not get_channel(chat.id):
        save_channel(chat.id, chat.title, added_by=update.effective_user.id)

    update_channel_field(chat.id, "photo_url", url)

    await update.message.reply_text(
        with_branding("✅ *Welcome photo updated!*"),
        parse_mode=ParseMode.MARKDOWN
    )


async def setvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    if not context.args:
        await update.message.reply_text("🎬 *Usage:* `/setvideo <video_url>`", parse_mode=ParseMode.MARKDOWN)
        return

    url = context.args[0]
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("❌ Provide a valid URL.")
        return

    if not get_channel(chat.id):
        save_channel(chat.id, chat.title, added_by=update.effective_user.id)

    update_channel_field(chat.id, "video_url", url)

    await update.message.reply_text(
        with_branding("✅ *Welcome video updated!*"),
        parse_mode=ParseMode.MARKDOWN
    )


async def toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    channel = get_channel(chat.id)
    if not channel:
        save_channel(chat.id, chat.title, added_by=update.effective_user.id)
        channel = get_channel(chat.id)

    new_state = 0 if channel[5] == 1 else 1
    update_channel_field(chat.id, "enabled", new_state)

    status = "✅ ON" if new_state == 1 else "❌ OFF"
    await update.message.reply_text(
        with_branding(f"⚙️ Welcome messages: *{status}*"),
        parse_mode=ParseMode.MARKDOWN
    )


async def react_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    channel = get_channel(chat.id)
    if not channel:
        save_channel(chat.id, chat.title, added_by=update.effective_user.id)
        channel = get_channel(chat.id)

    current = channel[6] if len(channel) > 6 else 1
    new_state = 0 if current == 1 else 1
    update_channel_field(chat.id, "auto_react", new_state)

    status = "✅ ON" if new_state == 1 else "❌ OFF"
    await update.message.reply_text(
        with_branding(
            f"💫 Auto-reactions: *{status}*\n\n"
            f"Emojis: {' '.join(CONFIG['REACTION_EMOJIS'])}"
        ),
        parse_mode=ParseMode.MARKDOWN
    )


async def remove_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat

    if chat.type not in ["channel", "supergroup", "group"]:
        await update.message.reply_text("❌ Use this command inside your channel.")
        return

    conn = sqlite3.connect(CONFIG["DB_FILE"])
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE chat_id = ?", (chat.id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        with_branding("🗑️ *Channel config removed.* Default settings active."),
        parse_mode=ParseMode.MARKDOWN
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode=ParseMode.MARKDOWN)
        return

    message = with_branding(" ".join(context.args))
    channels = get_all_channels()

    success = 0
    failed = 0

    for chat_id, title in channels:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            success += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        with_branding(f"📢 *Broadcast Complete!*\n\n✅ Sent: {success}\n❌ Failed: {failed}"),
        parse_mode=ParseMode.MARKDOWN
    )


# ============================================================
#                    CALLBACK HANDLER
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "help":
        await help_command(update, context)
    elif query.data == "about":
        await about(update, context)
    elif query.data == "setup":
        await setup(update, context)
    elif query.data == "chatid":
        await query.message.reply_text(
            with_branding(
                "🆔 *Chat ID Commands*\n\n"
                "• `/id` — All your IDs\n"
                "• `/chatid` — Current chat ID\n"
                "• `/userid` — Your user ID\n"
                "• `/channelid` — Forward a msg to get channel ID"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    elif query.data == "stats":
        await query.message.reply_text(
            with_branding("📊 Send /stats inside your channel."),
            parse_mode=ParseMode.MARKDOWN
        )


# ============================================================
#                    POST INIT
# ============================================================

async def post_init(app: Application):
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "How to use"),
        BotCommand("about", "About this bot"),
        BotCommand("id", "Get all your IDs"),
        BotCommand("chatid", "Get current chat ID"),
        BotCommand("userid", "Get your user ID"),
        BotCommand("channelid", "Get channel ID via forward"),
        BotCommand("setup", "Setup guide"),
        BotCommand("mywelcome", "View current welcome"),
        BotCommand("settext", "Set welcome text"),
        BotCommand("setphoto", "Set welcome photo"),
        BotCommand("setvideo", "Set welcome video"),
        BotCommand("toggle", "Enable/disable welcome"),
        BotCommand("react", "Toggle auto-reactions"),
        BotCommand("stats", "Channel statistics"),
        BotCommand("remove", "Remove channel config"),
    ]
    await app.bot.set_my_commands(commands)

    try:
        await app.bot.set_my_description(
            f"🤖 {CONFIG['BOT_NAME']}\n\n"
            "Channel manager + Chat ID tools + Auto reactions.\n\n"
            f"{CONFIG['COPYRIGHT']}"
        )
        await app.bot.set_my_short_description(
            "Channel manager bot by Fixo Dev"
        )
    except Exception as e:
        logger.warning(f"Description error: {e}")

    logger.info("✅ Bot commands and description set.")


# ============================================================
#                    MAIN
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    token = CONFIG["BOT_TOKEN"]
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        raise ValueError("❌ Set BOT_TOKEN in CONFIG!")

    init_db()
    logger.info("✅ Database initialized.")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    # Main commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about))

    # Chat ID commands
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("userid", userid))
    app.add_handler(CommandHandler("channelid", channelid))

    # Channel commands
    app.add_handler(CommandHandler("setup", setup))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mywelcome", mywelcome))
    app.add_handler(CommandHandler("settext", settext))
    app.add_handler(CommandHandler("setphoto", setphoto))
    app.add_handler(CommandHandler("setvideo", setvideo))
    app.add_handler(CommandHandler("toggle", toggle))
    app.add_handler(CommandHandler("react", react_toggle))
    app.add_handler(CommandHandler("remove", remove_config))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Callbacks
    app.add_handler(CallbackQueryHandler(button_handler))

    # Chat member welcome
    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    # Auto-reactions
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, auto_react_to_post))

    logger.info(f"🤖 {CONFIG['BOT_NAME']} starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
