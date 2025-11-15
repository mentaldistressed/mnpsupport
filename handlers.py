from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.error import TelegramError
import sqlite3
from config import DATABASE_FILE, CHANNEL_ID, allowed_ids, agents_chat_id
from db import get_last_agent_id, create_ticket, get_open_ticket, add_message_to_ticket, update_ticket_status, get_all_tickets, get_ticket_history, add_attachment, get_ticket_attachments, block_user, is_user_blocked, get_statistics, edit_ticket_message, get_tickets_by_user, get_ticket_by_id, get_block_reason, get_message_info, delete_message_from_history, get_user_id_by_ticket
from utils import status_mapping, QUICK_RESPONSES, AUTOANS
from typing import List, Tuple
import os
import time
import sys
import pytz
import hashlib
import re
import random
from datetime import datetime
import subprocess

access_enabled = True

def escape_markdown(text):
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

agent_numbers = {
    785092711: 3,
    7897895019: 2,
    5427059231: 1
}

def get_attachment_by_file_id(file_id):
    conn = sqlite3.connect('support.db')
    cursor = conn.cursor()

    cursor.execute("SELECT file_id FROM attachments WHERE file_id = ?", (file_id,))
    
    attachment = cursor.fetchone()

    conn.close()

    if attachment:
        return attachment[0]
    else:
        return None

def check_tickets(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if query:
        chat_id = query.message.chat_id
        page, user_id = map(int, query.data.split('_')[1:])
        query.answer()
    else:
        chat_id = update.effective_chat.id
        if chat_id != agents_chat_id:
            update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
            return

        args = context.args
        if len(args) != 1:
            update.message.reply_text("Использование: /check_tickets [Telegram ID]")
            return
        
        try:
            user_id = int(args[0])
            page = 0
        except ValueError:
            update.message.reply_text("ID пользователя должен быть числом.")
            return

    tickets = get_tickets_by_user(user_id)
    if tickets:
        tickets.reverse()

        paginated_tickets, has_next_page = paginate_tickets(tickets, page)
        response = f"📋 Обращения пользователя с ID <code>{user_id}</code>:\n\n"
        for ticket in paginated_tickets:
            ticket_id, _, status, message, response_text, username = ticket
            if status == '1':
                response += f'⚪️ №{ticket_id}. Статус: <b>🟢 {status_mapping[status]}</b>, Сообщение: {message}\n'
            elif status == '2':
                response += f'⚪️ №{ticket_id}. Статус: <b>🟡 {status_mapping[status]}</b>, Сообщение: {message}\n'
            elif status == '3':
                response += f'⚪️ №{ticket_id}. Статус: <b>🔴 {status_mapping[status]}</b>, Сообщение: {message}\n'

        buttons = create_pagination_buttons(page, has_next_page)
        if query:
            query.edit_message_text(response, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            update.message.reply_text(response, parse_mode=ParseMode.HTML, reply_markup=buttons)
    else:
        if query:
            query.edit_message_text(f'❌ У пользователя с ID {user_id} нет обращений', parse_mode=ParseMode.HTML)
        else:
            update.message.reply_text(f'❌ У пользователя с ID {user_id} нет обращений')

def check_block(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    args = context.args
    if len(args) < 1:
        update.message.reply_text("Использование: /check_block [ID пользователя]")
        return

    try:
        user_id = int(args[0])
        block_reason = get_block_reason(user_id)

        if block_reason:
            update.message.reply_text(
                f"🔒 Пользователь с ID <code>{user_id}</code> заблокирован.\nПричина: <b>{block_reason}</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            update.message.reply_text(
                f"✅ Пользователь с ID <code>{user_id}</code> не заблокирован.",
                parse_mode=ParseMode.HTML
            )

    except ValueError:
        update.message.reply_text("❌ Указан некорректный ID пользователя. Используйте числовой ID.")
    except Exception as e:
        update.message.reply_text(f"❌ Произошла ошибка: {e}")

def attach(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) < 1:
        update.message.reply_text('Использование: /attach [ID файла]')
        return
    
    file_id = args[0]
    attachment = get_attachment_by_file_id(file_id)

    if not attachment:
        update.message.reply_text(f'❌ Вложение с ID {file_id} не найдено.')
        return

    context.bot.send_photo(chat_id=chat_id, photo=attachment)

def unblock(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    args = context.args
    if not args:
        update.message.reply_text("Использование: /unblock [Telegram ID]")
        return

    user_id = int(args[0])
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM blocks WHERE user_id = ?", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

    update.message.reply_text(f"✅ Пользователь {user_id} разблокирован")

def block_list(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, reason, agent_id FROM blocks")
    blocks = cursor.fetchall()
    cursor.close()
    conn.close()

    if not blocks:
        update.message.reply_text("🔹 Нет заблокированных пользователей")
        return

    response = "🔒 Список заблокированных пользователей:\n\n"
    for user_id, reason, agent_id in blocks:
        agent_number = agent_id
        response += f"👤 {user_id} — Причина: {reason} — Выдано агентом #{agent_number}\n"

    update.message.reply_text(response)

def stats(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    statistics = get_statistics()

    response = (
        "📊 <b>Статистика</b>:\n\n"
        "📝 <b>Обращения:</b>\n"
        f"• Открыто: <b>{statistics['open_tickets']} ({', '.join(map(str, statistics['open_ticket_ids']))})</b>\n"
        f"• В обработке: <b>{statistics['in_process_tickets']} ({', '.join(map(str, statistics['in_process_ticket_ids']))})</b>\n"
        f"• Закрыто: <b>{statistics['closed_tickets']}</b>\n"
        f"• Всего: <b>{statistics['total_tickets']}</b>\n\n"
        "✉️ <b>Сообщения:</b>\n"
        f"• От агентов поддержки: <b>{statistics['agent_messages']}</b>\n"
        f"• От юзеров: <b>{statistics['user_messages']}</b>\n"
        f"• Всего: <b>{statistics['total_messages']}</b>\n\n"
        "👥 <b>Пользователи:</b>\n"
        f"• Всего: <b>{statistics['total_users']}</b>"
    )

    update.message.reply_text(response, parse_mode=ParseMode.HTML)

def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
    if chat_id == agents_chat_id:
        return
    if is_user_blocked(user_id):
        update.message.reply_text(f'🚫 У Вас ограничен доступ к написанию обращений в техническую поддержку')
        return
    try:
        if access_enabled or update.message.from_user.id in allowed_ids:
            chat_member = context.bot.get_chat_member(CHANNEL_ID, update.message.from_user.id)
            if chat_member.status in ("member", "administrator", "creator"):
                message = '👋 Привет! Нужна помощь или у Вас возникли вопросы? Опишите, пожалуйста, суть обращения максимально подробно. Наши агенты технической поддержки с удовольствием Вам помогут!\n\n🔐 Не удается войти в игровой аккаунт? Воспользуйтесь ссылкой для восстановления доступа: https://mn-p.com (нажмите кнопку «Не можете войти?» в правом верхнем углу страницы)'
                context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            else:
                keyboard = [
                    [InlineKeyboardButton("👉 Подписаться на канал", url=f"https://t.me/gta_mn")],
                    [InlineKeyboardButton("🚀 Запустить бота", callback_data='start')],]
                reply_markup = InlineKeyboardMarkup(keyboard)
                update.message.reply_text('⚠️ Для начала взаимодействия с помощником Вам необходимо подписаться на наш новостной канал', reply_markup=reply_markup)
        else:
            update.message.reply_text('🚫 Доступ к использованию бота для Вас ограничен. Пожалуйста, обратитесь к администратору для получения доступа')
    except TelegramError as e:
        update.message.reply_text('🛠 Произошёл внутренний сбой, пожалуйста, совершите попытку позже')
        print(e)

def hhelp(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return
    
    response = f'❓ Функционал агента поддержки:\n\n/view — просмотр всех обращений\n/hhelp — команды, доступные для агента поддержки\n/ansid [Telegram ID] [сообщение] — сообщение пользователю по TG ID\n/ans [ID обращения] [сообщение] — ответ на обращение\n/edit [ID сообщения] [Новое сообщение] — редактирование сообщения\n/attach [ID вложения] — просмотр конкретного вложения\n/history [ID обращения] — просмотр сообщений во всём обращении\n/check_tickets [ID пользователя] — просмотр всех обращений пользователя\n/status [ID обращения] [новый статус (1 - open, 2 - pending, 3 - closed)] —  смена статуса обращения\n/block [Telegram ID] [Причина блокировки] — ограничить пользователя в создании новых обращений\n/unblock [Telegram ID] — снять с пользователя ограничение в создании новых обращений\n/block_list — просмотр списка заблокированных пользователей'
    update.message.reply_text(response)

def block(update: Update, context: CallbackContext) -> None:
    if update.message.chat_id != agents_chat_id:
        return

    args = context.args
    if len(args) < 2:
        update.message.reply_text('Использование: /block [Telegram ID] [Причина]')
        return

    try:
        user_id = int(args[0])
        reason = ' '.join(args[1:])
        agent_id = get_agent_number(update.message.from_user.id)

        user_info = context.bot.get_chat(user_id)
        blocked_username = user_info.username if user_info.username else 'unknown'

        block_user(user_id, reason, agent_id)
        update.message.reply_text(
            f'‼️ Выдана блокировка пользователю @{blocked_username} (Telegram ID: {user_id}): {reason}'
        )
        context.bot.send_message(
            chat_id=user_id,
            text=f'🚫 Вам ограничили доступ к написанию обращений в техническую поддержку. Причина: {reason}'
        )

    except ValueError:
        update.message.reply_text('Некорректный ID пользователя.')
    except Exception as e:
        update.message.reply_text(f'Произошла ошибка: {e}')

def rating_stats(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    if chat_id != agents_chat_id:
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM ratings")
        total_ratings = cursor.fetchone()[0]
        if total_ratings == 0:
            update.message.reply_text("😔 Пока нет ни одной оценки.")
            return

        cursor.execute("""
            SELECT agent_id, 
                   ROUND(AVG(rating), 2) AS avg_rating,
                   COUNT(*) AS total_ratings
            FROM ratings
            GROUP BY agent_id
            ORDER BY total_ratings DESC, avg_rating DESC
        """)
        agents = cursor.fetchall()
        cursor.close()
        conn.close()

        response = "📊 <b>Рейтинг агентов поддержки</b>\n\n"

        for position, (agent_id, avg_rating, total_ratings) in enumerate(agents, start=1):
            agent_number = agent_id
            stars = "⭐" * int(round(avg_rating)) + "☆" * (5 - int(round(avg_rating)))

            if position == 1:
                medal = "🥇"
            elif position == 2:
                medal = "🥈"
            elif position == 3:
                medal = "🥉"
            else:
                medal = "⚙️"

            response += (
                f"{medal} <b>Агент #{agent_number}</b>\n"
                f" {stars} ({avg_rating}/5)\n"
                f" 🧾 Оценок: {total_ratings}\n\n"
            )

        update.message.reply_text(response, parse_mode=ParseMode.HTML)

    except sqlite3.Error as e:
        update.message.reply_text(f"Ошибка при получении статистики: {e}")

def handle_video(update: Update, context: CallbackContext) -> None:
    update.message.reply_text("❌ К сожалению, отправка видео недоступна. Пожалуйста, загрузите его на YouTube и предоставьте ссылку для просмотра")

def handle_message(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
    message_text = update.message.text

    if chat_id == agents_chat_id:
        return

    if is_user_blocked(user_id):
        update.message.reply_text('🚫 Вам ограничен доступ к написанию обращений в техническую поддержку')
        return

    lowered = message_text.lower()

    for keyword, auto_text in AUTOANS.items():
        keyword_words = keyword.lower().split()

        if all(word in lowered for word in keyword_words):

            keyboard = [[InlineKeyboardButton("Вызвать агента поддержки", callback_data="call_agent")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            update.message.reply_text(auto_text, reply_markup=reply_markup, parse_mode="HTML")

            agent_notice = (
                f"🤖 <b>Сработал автоответ</b>\n\n"
                f"👤 Пользователь: @{update.message.from_user.username} (ID: <code>{user_id}</code>)\n"
                f"💬 Сообщение: <i>{message_text}</i>\n\n"
                f"🔑 Ключ: <b>{keyword}</b>\n"
                f"📤 Ответ бота: <i>{auto_text}</i>"
            )

            context.bot.send_message(
                chat_id=agents_chat_id,
                text=agent_notice,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )

            return

    try:
        if access_enabled or update.message.from_user.id in allowed_ids:
            chat_member = context.bot.get_chat_member(CHANNEL_ID, update.message.from_user.id)
            if chat_member.status in ("member", "administrator", "creator"):
                if update.message.video:
                    update.message.reply_text("❌ К сожалению, отправка видео недоступна. Пожалуйста, загрузите его на YouTube и предоставьте ссылку для просмотра")
                    return

                conn = sqlite3.connect(DATABASE_FILE)
                cursor = conn.cursor()
                ticket = get_open_ticket(user_id)

                if ticket:
                    ticket_id = ticket[0]
                    add_message_to_ticket(ticket_id, 'user', message_text, None, None)
                    notification_text = (
                        f'🔔 Добавлено сообщение к обращению №{ticket_id} от пользователя @{update.message.from_user.username} '
                        f'(Telegram ID: {update.message.from_user.id}): {message_text}'
                    )
                    update.message.reply_text('✉️ Ваше сообщение отправлено агентам поддержки, ожидайте ответа')

                else:
                    ticket_id = create_ticket(user_id, '1', message_text, update.message.from_user.username)
                    notification_text = (
                        f'🔔 Создано обращение №{ticket_id} от пользователя @{update.message.from_user.username} '
                        f'(Telegram ID: {update.message.from_user.id}): {message_text}'
                    )
                    update.message.reply_text('✉️ Агенты поддержки получили Ваше обращение, пожалуйста, ожидайте ответа')

            else:
                keyboard = [
                    [InlineKeyboardButton("👉 Подписаться на канал", url="https://t.me/gta_mn")],
                    [InlineKeyboardButton("🚀 Запустить бота", callback_data='start')],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                update.message.reply_text('⚠️ Для начала взаимодействия с помощником Вам необходимо подписаться на наш новостной канал', reply_markup=reply_markup)

        context.bot.send_message(chat_id=agents_chat_id, text=notification_text)

    except sqlite3.Error as e:
        print(f'Ошибка работы с базой данных: {e}')

def handle_photo(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
    photo_file = update.message.photo[-1].file_id
    if is_user_blocked(user_id):
        update.message.reply_text(f'🚫 У Вас ограничен доступ к написанию обращений в техническую поддержку')
        return
    if chat_id == agents_chat_id:
        return
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        open_ticket = get_open_ticket(user_id)

        ticket = get_open_ticket(user_id)
        if ticket:
            ticket_id = ticket[0]
            ticketusername = update.message.from_user.username
            add_attachment(open_ticket[0], photo_file)
            add_message_to_ticket(ticket_id, 'user', '*Вложение*', None, None)
            notification_text = (f'📷 Добавлена фотография к обращению №{ticket_id} от пользователя @{update.message.from_user.username} (Telegram ID: {update.message.from_user.id}) (File ID: <code>{photo_file}</code>)')
            update.message.reply_text('✉️ Агенты поддержки получили Ваше обращение, пожалуйста, ожидайте ответа')
        else:
            ticket_id = create_ticket(user_id, '1', '*Вложение*', update.message.from_user.username)
            add_attachment(ticket_id, photo_file)
            notification_text = (f'📷 Создано обращение с фотографией №{ticket_id} от пользователя @{update.message.from_user.username} (Telegram ID: {update.message.from_user.id}) (File ID: <code>{photo_file}</code>)')
            update.message.reply_text('✉️ Агенты поддержки получили Ваше обращение, пожалуйста, ожидайте ответа')

        context.bot.send_message(chat_id=agents_chat_id, text=notification_text, parse_mode=ParseMode.HTML)

    except sqlite3.Error as e:
        print(f'Ошибка работы с базой данных: {e}')

    finally:
        cursor.close()
        conn.close()

def reboot(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    if user_id not in allowed_ids:
        update.message.reply_text('❌ У Вас нет прав для выполнения этой команды')
        return

    update.message.reply_text('🔄 Обновление кода с Git и перезапуск бота...')

    try:
        result = subprocess.run(['git', 'pull', 'origin', 'main'], capture_output=True, text=True)
        output_lines = result.stdout.splitlines() + result.stderr.splitlines()

        filtered_lines = []
        for line in output_lines:
            line = line.strip()
            if line == "Already up to date.":
                filtered_lines.append(line)
            elif line.startswith("* branch"):
                filtered_lines.append(line)
            elif "changed" in line or ("insertions" in line or "deletions" in line):
                filtered_lines.append(line)

        filtered_output = "\n".join(filtered_lines)

        update.message.reply_text(f'📥 Результат git pull:\n<pre>{filtered_output[:4000]}</pre>', parse_mode=ParseMode.HTML)
    except Exception as e:
        update.message.reply_text(f'❌ Ошибка при выполнении git pull: {e}')

    python = sys.executable
    os.execl(python, python, *sys.argv)

def delete_message(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        return

    args = context.args
    if len(args) < 1:
        update.message.reply_text("Использование: /delete [ID сообщения]")
        return

    try:
        message_id = int(args[0])

        success, user_message_id, ticket_id = get_message_info(message_id)

        if success:
            user_chat_id = get_user_id_by_ticket(ticket_id)
            if user_message_id:
                try:
                    context.bot.delete_message(chat_id=user_chat_id, message_id=user_message_id)
                except Exception as e:
                    update.message.reply_text(f"Ошибка удаления: {e}")
                    return
            
            delete_message_from_history(message_id)

            update.message.reply_text(f"✅ Сообщение с ID {message_id} удалено")
        else:
            update.message.reply_text(f"❌ Сообщение с ID {message_id} не найдено")

    except ValueError:
        update.message.reply_text("❌ Ошибка: ID сообщения должен быть числом")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {e}")

def edit(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        return
    args = context.args
    if len(args) < 2:
        update.message.reply_text("Использование: /edit [ID сообщения] [Новое сообщение]")
        return
    
    try:
        message_id = int(args[0])
        agent_id = update.message.from_user.id
        agent_number = str(agent_numbers.get(agent_id, 'без номера'))
        new_message = ' '.join(args[1:])
        final_message = '👨‍💻 Агент поддержки #' + agent_number + ': ' + new_message

        success, user_message_id, ticket_id = edit_ticket_message(message_id, new_message)

        if success:
            user_chat_id = get_user_id_by_ticket(ticket_id)
            if user_message_id:
                try:
                    context.bot.edit_message_text(
                        chat_id=user_chat_id,
                        message_id=user_message_id,
                        text=final_message,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    print(e)
            update.message.reply_text(f"✅ Сообщение с ID {message_id} отредактировано")
        else:
            update.message.reply_text(f"❌ Сообщение с ID {message_id} не найдено")
        
    except ValueError:
        update.message.reply_text("❌ Ошибка: ID сообщения должен быть числом")
    except Exception as e:
        update.message.reply_text(f"❌ Ошибка: {e}")

def qinfo(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    response = "📝 Доступные быстрые ответы:\n\n"
    for quick_response_id, quick_response in QUICK_RESPONSES.items():
        response += f"<b>{quick_response_id}.</b> {quick_response}\n\n"
    
    update.message.reply_text(response, parse_mode=ParseMode.HTML)

def quick_answer_ticket(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        return

    args = context.args
    if len(args) < 2:
        update.message.reply_text('Использование: /qans [ID обращения] [Номер быстрого ответа]')
        return

    try:
        ticket_id = int(args[0])
        quick_response_id = int(args[1])

        if quick_response_id not in QUICK_RESPONSES:
            update.message.reply_text('❌ Неверный номер быстрого ответа')
            return

        response = QUICK_RESPONSES[quick_response_id]
        ticket = get_ticket_by_id(ticket_id)
        user_id, status = ticket['user_id'], ticket['status']
        agent_id = update.message.from_user.id
        agent_number = agent_numbers.get(agent_id, 'без номера')

        if status == '3':
            update.message.reply_text(
                '❌ Вы не можете ответить на данное обращение, поскольку оно <b>закрыто</b>',
                parse_mode=ParseMode.HTML
            )
            return

        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        cursor.execute('SELECT user_id FROM tickets WHERE id = ?', (ticket_id,))
        user_id = cursor.fetchone()[0]

        user_message = context.bot.send_message(chat_id=user_id, text=f'👨‍💻 Агент поддержки #{agent_number}: {response}', parse_mode=ParseMode.HTML)
        user_message_id = user_message.message_id

        message_id = add_message_to_ticket(ticket_id, 'agent', response, agent_id, user_message_id)

        update.message.reply_text(f'✉️ Быстрый ответ №{quick_response_id} на обращение №{ticket_id} успешно отправлен (ID: {message_id})')

    except ValueError:
        update.message.reply_text('❌ Неверный формат ввода. Используйте: /qans [ID обращения] [Номер быстрого ответа]')
    except sqlite3.Error as e:
        update.message.reply_text(f'Ошибка работы с базой данных: {e}')
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()


def answer_ticket(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        return

    args = context.args
    if len(args) < 2:
        update.message.reply_text('Использование: /ans [ID обращения] [ответ]')
        return

    ticket_id = int(args[0])
    response = update.message.text.partition(' ')[2].partition(' ')[2]
    ticket = get_ticket_by_id(ticket_id)
    user_id, status = ticket['user_id'], ticket['status']
    agent_id = update.message.from_user.id
    agent_number = agent_numbers.get(agent_id, 'без номера')

    if status == '3':
        update.message.reply_text(
            '❌ Вы не можете ответить на данное обращение, поскольку оно <b>закрыто</b>',
            parse_mode=ParseMode.HTML
        )
        return

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, id FROM tickets WHERE id = ?', (ticket_id,))
        user_id = cursor.fetchone()[0]
        
        user_message = context.bot.send_message(chat_id=user_id, text=f'👨‍💻 Агент поддержки #{agent_number}: {response}', parse_mode=ParseMode.HTML)
        user_message_id = user_message.message_id

        message_id = add_message_to_ticket(ticket_id, 'agent', response, agent_id, user_message_id)

        update.message.reply_text(f'✉️ Ответ на обращение №{ticket_id} успешно отправлен (ID: {message_id})')

    except sqlite3.Error as e:
        update.message.reply_text(f'Ошибка работы с базой данных: {e}')

    finally:
        cursor.close()
        conn.close()

def change_ticket_status(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        return

    args = context.args
    if len(args) < 2:
        update.message.reply_text('Использование: /status [ID обращения] [новый статус (1 - open, 2 - pending, 3 - closed)]')
        return

    ticket_id = int(args[0])
    new_status = args[1]

    if new_status not in ['1', '2', '3']:
        update.message.reply_text('❌ Некорректный статус: 1 (open), 2 (pending), 3 (closed)')
        return

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM tickets WHERE id = ?', (ticket_id,))
        user_id = cursor.fetchone()[0]

        update_ticket_status(ticket_id, new_status)
        context.bot.send_message(
            parse_mode=ParseMode.HTML,
            chat_id=user_id,
            text=f'🔔 Вашему обращению (№{ticket_id}) присвоен статус <b>«{status_mapping[new_status]}»</b>'
        )

        update.message.reply_text(
            f'🔔 Обращению №{ticket_id} присвоен статус <b>«{status_mapping[new_status]}»</b>',
            parse_mode=ParseMode.HTML
        )

        if new_status == '3':
            keyboard = [
                [InlineKeyboardButton("1 ⭐️", callback_data=f"rate_{ticket_id}_1"),
                 InlineKeyboardButton("2 ⭐️ ", callback_data=f"rate_{ticket_id}_2"),
                 InlineKeyboardButton("3 ⭐️", callback_data=f"rate_{ticket_id}_3"),
                 InlineKeyboardButton("4 ⭐️", callback_data=f"rate_{ticket_id}_4"),
                 InlineKeyboardButton("5 ⭐️", callback_data=f"rate_{ticket_id}_5")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            context.bot.send_message(chat_id=user_id, text="⭐ Пожалуйста, оцените работу агента:", reply_markup=reply_markup)

    except sqlite3.Error as e:
        update.message.reply_text(f'Ошибка работы с базой данных: {e}')

    finally:
        cursor.close()
        conn.close()

def paginate_tickets(tickets, page, items_per_page=15):
    start = page * items_per_page
    end = start + items_per_page
    return tickets[start:end], len(tickets) > end

def create_pagination_buttons(page, has_next_page):
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"tickets_{page-1}"))
    if has_next_page:
        buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"tickets_{page+1}"))
    return InlineKeyboardMarkup([buttons])

def view_tickets(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    if query:
        chat_id = query.message.chat_id
        page = int(query.data.split('_')[1])
        query.answer()
    else:
        chat_id = update.effective_chat.id
        page = 0

    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    tickets = get_all_tickets()
    if tickets:
        tickets.reverse()
        
        paginated_tickets, has_next_page = paginate_tickets(tickets, page)
        response = "📋 Все обращения:\n\n"
        for ticket in paginated_tickets:
            ticket_id, user_id, status, message, username = ticket
            if status == '1':
                response += f'⚪️ №{ticket_id}. Обращение от пользователя @{username} с ID <code>{user_id}</code>, имеющее статус <b>«🟢 {status_mapping[status]}»</b>: {message}\n'
            elif status == '2':
                response += f'⚪️ №{ticket_id}. Обращение от пользователя @{username} с ID <code>{user_id}</code>, имеющее статус <b>«🟡 {status_mapping[status]}»</b>: {message}\n'
            elif status == '3':
                response += f'⚪️ №{ticket_id}. Обращение от пользователя @{username} с ID <code>{user_id}</code>, имеющее статус <b>«🔴 {status_mapping[status]}»</b>: {message}\n'
        
        buttons = create_pagination_buttons(page, has_next_page)
        if query:
            query.edit_message_text(response, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            update.message.reply_text(response, parse_mode=ParseMode.HTML, reply_markup=buttons)
    else:
        if query:
            query.edit_message_text('❌ Обращения не найдены', parse_mode=ParseMode.HTML)
        else:
            update.message.reply_text('❌ Обращения не найдены')

def ansid(update, context):
    chat_id = update.effective_chat.id

    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    args = context.args
    if len(args) < 2:
        update.message.reply_text("Использование: /ansid [user_id] [сообщение]")
        return
    
    try:
        user_id = int(args[0])
        message = " ".join(args[1:])
        context.bot.send_message(chat_id=user_id, text=f"👨‍💻 Агент поддержки: {message}")
    except ValueError:
        update.message.reply_text("Неверный формат user_id.")   

def convert_to_gmt3(utc_time_str):
    utc_time = datetime.strptime(utc_time_str, '%Y-%m-%d %H:%M:%S')
    utc_time = utc_time.replace(tzinfo=pytz.utc)
    gmt3_time = utc_time.astimezone(pytz.timezone('Europe/Moscow'))
    return gmt3_time.strftime('%Y-%m-%d %H:%M:%S')

def convert_to_timezone(timestamp_str, timezone):
    try:
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise ValueError(f"Неверный формат времени: {timestamp_str}")

    timestamp = timestamp.replace(tzinfo=pytz.utc)

    local_time = timestamp.astimezone(pytz.timezone(timezone))
    return local_time.strftime('%Y-%m-%d %H:%M:%S')

def get_agent_number(agent_id):
    if agent_id == 7897895019:
        return 2
    elif agent_id == 5427059231:
        return 1
    elif agent_id == 785092711:
        return 3
    else:
        return "?"
    
def history(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if chat_id != agents_chat_id:
        update.message.reply_text('❌ У вас нет прав для выполнения этой команды')
        return

    args = context.args
    if len(args) < 1:
        update.message.reply_text('Использование: /history [ID обращения]')
        return
    
    ticket_id = int(args[0])
    messages = get_ticket_history(ticket_id)
    attachments = get_ticket_attachments(ticket_id)

    if messages:
        response = ''
        attachment_count = 1

        for message in messages:
            message_id = message[0]  # ID сообщения в истории
            user_message_id = message[6]  # ID сообщения у пользователя
            timestamp_gmt3 = convert_to_gmt3(message[4])
            sender_type = message[2]
            message_text = message[3]

            if sender_type == 'user':
                sender = 'Пользователь'
            else:
                agent_id = message[5]
                agent_number = get_agent_number(agent_id)
                sender = f'👨‍💻 Агент поддержки #{agent_number}'

                if user_message_id:
                    message_text += f' <b>(ID: {user_message_id})</b>'

            response += f'[{timestamp_gmt3}] — {sender}: {message_text}\n'

        max_message_length = 4096
        response_lines = response.split('\n')
        chunk = ''

        for line in response_lines:
            if len(chunk) + len(line) + 1 <= max_message_length:
                chunk += line + '\n'
            else:
                update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
                time.sleep(1)
                chunk = line + '\n'
        
        if chunk:
            update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
            time.sleep(1)

        for attachment in attachments:
            file_id = attachment[2]
            escaped_file_id = escape_markdown(file_id)
            time.sleep(1)
            context.bot.send_message(chat_id=chat_id, text=f'📸 Вложение №{attachment_count}', parse_mode=ParseMode.MARKDOWN)
            context.bot.send_photo(chat_id=chat_id, photo=attachment[2])
            attachment_count += 1
            
    else:
        update.message.reply_text(f'История для обращения с ID {ticket_id} не найдена')

def button_callback(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    query = update.callback_query
    query.answer()

    response = None

    if query.data.startswith("rate_"):
        try:
            _, ticket_id_str, rating_str = query.data.split('_')
            ticket_id = int(ticket_id_str)
            rating = int(rating_str)
            user_id = query.from_user.id

            agent_id = get_agent_number(get_last_agent_id(ticket_id))
            if not agent_id:
                response = "❌ Не удалось определить агента для оценки"
            else:
                conn = sqlite3.connect(DATABASE_FILE)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO ratings (ticket_id, agent_id, user_id, rating) VALUES (?, ?, ?, ?)",
                    (ticket_id, agent_id, user_id, rating)
                )
                conn.commit()
                cursor.close()
                conn.close()

                response = f"Спасибо за оценку! Вы поставили {rating}⭐️"

                context.bot.send_message(
                    chat_id=agents_chat_id,
                    text=f"🔔 Пользователь <b>{user_id}</b> оценил работу агента #<b>{agent_id}</b> по тикету №{ticket_id} на {rating}⭐️",
                    parse_mode=ParseMode.HTML
                )

        except Exception as e:
            response = f"❌ Ошибка при сохранении оценки: {e}"
    if query.data == "call_agent":
        query.edit_message_text("🛎 Пожалуйста, опишите свою проблему, и я вызову агента поддержки.")
        return
    if query.data == 'all_tickets':
        tickets = get_all_tickets()
        if tickets:
            response = "📋 Все обращения:\n\n"
            for ticket in tickets:
                ticket_id, user_id, status, message, username = ticket
                if status == '1':
                    response += f'⚪️ №{ticket_id}. Обращение от пользователя @{username} с ID <code>{user_id}</code>, имеющее статус <b>«🟢 {status_mapping[status]}»</b>: {message}\n'
                elif status == '2':
                    response += f'⚪️ №{ticket_id}. Обращение от пользователя @{username} с ID <code>{user_id}</code>, имеющее статус <b>«🟡 {status_mapping[status]}»</b>: {message}\n'
                elif status == '3':
                    response += f'⚪️ №{ticket_id}. Обращение от пользователя @{username} с ID <code>{user_id}</code>, имеющее статус <b>«🔴 {status_mapping[status]}»</b>: {message}\n'
    elif query.data.startswith("tickets_"):
        view_tickets(update, context)
    elif query.data == 'start':
        chat_id = update.effective_chat.id
        if chat_id == agents_chat_id:
            return
        try:
            if access_enabled or chat_id in allowed_ids:
                chat_member = context.bot.get_chat_member(CHANNEL_ID, chat_id)
                if chat_member.status in ("member", "administrator", "creator"):
                    response = '👋 Привет! Нужна помощь или у Вас возникли вопросы? Опишите, пожалуйста, суть обращения максимально подробно. Наши агенты технической поддержки с удовольствием Вам помогут!\n\n🔐 Не удается войти в игровой аккаунт? Воспользуйтесь ссылкой для восстановления доступа: https://mn-p.com (нажмите кнопку «Не можете войти?» в правом верхнем углу страницы)'
                else:
                    keyboard = [
                        [InlineKeyboardButton("👉 Подписаться на канал", url=f"https://t.me/gta_mn")],
                        [InlineKeyboardButton("🚀 Запустить бота", callback_data='start')],]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    response = '🤨 Похоже, Вы всё ещё не подписались на наш новостной канал. Пожалуйста, сделайте это, чтобы продолжить взаимодействие с технической поддержкой'
                    query.edit_message_text(response, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                    return
            else:
                response = '🚫 Доступ к использованию бота для Вас ограничен. Пожалуйста, обратитесь к администратору для получения доступа'
        except TelegramError as e:
            response = '🛠 Произошёл внутренний сбой, пожалуйста, совершите попытку позже'
            print(e)
    else:
        print('Неизвестная кнопка')
    if response is not None:
        query.edit_message_text(response, parse_mode=ParseMode.HTML, disable_web_page_preview=True)