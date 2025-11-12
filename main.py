from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, CallbackContext
from config import TOKEN, agents_chat_id, DATABASE_FILE, backup_chat_id
from handlers import fileid, start, handle_message, answer_ticket, change_ticket_status, view_tickets, button_callback, history, handle_photo, ansid, handle_video, reboot, block, stats, edit, hhelp, check_tickets, quick_answer_ticket, qinfo, check_block, delete_message, block_list
import os
import threading
import time
import sys
import logging

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def notify_agents(context: CallbackContext):
    context.bot.send_message(chat_id=agents_chat_id, text="✅ Выполнен запуск/перезагрузка поллинга, текущая версия: 0.0.0-debug. Резервные копирования: включены")

def stop_polling_notification(updater: Updater) -> None:
    updater.bot.send_message(
        chat_id=agents_chat_id,
        text="🔴 Выполнена остановка поллинга, текущая версия: 0.0.0-debug."
    )

def send_backup(bot) -> None:
    try:
        bot.send_document(chat_id=backup_chat_id, document=open(DATABASE_FILE, 'rb'))
    except Exception as e:
        print(f"Ошибка при отправке резервной копии: {e}")

def backup_scheduler(updater: Updater) -> None:
    while True:
        send_backup(updater.bot)
        time.sleep(43200) # кд бекапы время секунды

def main():
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("ans", answer_ticket))
    dispatcher.add_handler(CommandHandler("status", change_ticket_status))
    dispatcher.add_handler(CommandHandler("view", view_tickets))
    dispatcher.add_handler(CommandHandler("history", history))
    dispatcher.add_handler(CommandHandler("hhelp", hhelp))
    dispatcher.add_handler(CommandHandler("ansid", ansid))
    dispatcher.add_handler(CommandHandler("stats", stats))
    dispatcher.add_handler(CommandHandler("reboot", reboot))
    dispatcher.add_handler(CommandHandler("block", block))
    dispatcher.add_handler(CommandHandler("fileid", fileid))
    dispatcher.add_handler(CommandHandler("edit", edit))
    dispatcher.add_handler(CommandHandler("check_tickets", check_tickets))
    dispatcher.add_handler(CommandHandler('qans', quick_answer_ticket))
    dispatcher.add_handler(CommandHandler('qinfo', qinfo))
    dispatcher.add_handler(CommandHandler('check_block', check_block))
    dispatcher.add_handler(CommandHandler('delete', delete_message))
    dispatcher.add_handler(CommandHandler('block_list', block_list))

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.video, handle_video))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
    dispatcher.add_handler(CallbackQueryHandler(button_callback))

    updater.job_queue.run_once(notify_agents, when=0)

    backup_thread = threading.Thread(target=backup_scheduler, args=(updater,))
    backup_thread.daemon = True
    backup_thread.start()

    try:
        updater.start_polling()
        updater.idle()
    finally:
        stop_polling_notification(updater)
        python = sys.executable
        os.execlp('python3', 'python3', *os.path.abspath(__file__))
    
    python = sys.executable    
    os.execlp('python3', 'python3', *os.path.abspath(__file__))

if __name__ == '__main__':
    main()