import os
import logging

from datetime import datetime, timedelta
from dateutil import parser
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
)
import firebase_admin
from firebase_admin import credentials, firestore

# Настройка Firebase
cred = credentials.Certificate("bomsams-e0996-firebase-adminsdk-fbsvc-64de839fde.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Настройка логов
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
GROUP_NAME, GROUP_PASSWORD, JOIN_GROUP, JOIN_PASSWORD, EVENT_DATE, EVENT_START, EVENT_END, EVENT_LOCATION = range(8)

# Команда /start
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "🍴 Бот для организации совместных обедов!\n"
        "Создайте группу: /create\n"
        "Присоединиться к группе: /join\n"
        "Добавить запись: /addevent\n"
        "Текущие записи: /current\n"
        "История: /history"
    )

# Создание группы
async def create_group(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Введите название группы:")
    return GROUP_NAME

async def process_group_name(update: Update, context: CallbackContext) -> int:
    context.user_data['group_name'] = update.message.text
    await update.message.reply_text("Введите пароль для группы:")
    return GROUP_PASSWORD

async def process_group_password(update: Update, context: CallbackContext) -> int:
    group_name = context.user_data['group_name']
    password = update.message.text
    user_id = update.message.from_user.id

    # Создание группы в Firestore
    db.collection('groups').document(group_name).set({
        'password': password,
        'members': [user_id]
    })

    await update.message.reply_text(f"✅ Группа '{group_name}' создана!")
    return ConversationHandler.END

# Присоединение к группе
async def join_group(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Введите название группы:")
    return JOIN_GROUP

async def process_join_group(update: Update, context: CallbackContext) -> int:
    context.user_data['join_group'] = update.message.text
    await update.message.reply_text("Введите пароль группы:")
    return JOIN_PASSWORD

async def process_join_password(update: Update, context: CallbackContext) -> int:
    group_name = context.user_data['join_group']
    password = update.message.text
    user_id = update.message.from_user.id

    group_ref = db.collection('groups').document(group_name)
    group = group_ref.get()

    if not group.exists:
        await update.message.reply_text("❌ Группа не найдена!")
        return ConversationHandler.END

    if group.to_dict()['password'] != password:
        await update.message.reply_text("❌ Неверный пароль!")
        return ConversationHandler.END

    # Добавление пользователя в группу
    group_ref.update({"members": firestore.ArrayUnion([user_id])})
    await update.message.reply_text(f"✅ Вы присоединились к группе '{group_name}'!")
    return ConversationHandler.END

# Добавление события
async def add_event(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Введите дату (например, 2023-10-10):")
    return EVENT_DATE

async def process_event_date(update: Update, context: CallbackContext) -> int:
    try:
        date = parser.parse(update.message.text).date()
        context.user_data['event_date'] = date
        await update.message.reply_text("Введите время начала (например, 13:00):")
        return EVENT_START
    except:
        await update.message.reply_text("❌ Неверный формат даты! Попробуйте еще раз.")
        return EVENT_DATE

async def process_event_start(update: Update, context: CallbackContext) -> int:
    try:
        start_time = parser.parse(update.message.text).time()
        context.user_data['event_start'] = start_time
        await update.message.reply_text("Введите время окончания (например, 14:00):")
        return EVENT_END
    except:
        await update.message.reply_text("❌ Неверный формат времени! Попробуйте еще раз.")
        return EVENT_START

async def process_event_end(update: Update, context: CallbackContext) -> int:
    try:
        end_time = parser.parse(update.message.text).time()
        context.user_data['event_end'] = end_time
        await update.message.reply_text("Введите место:")
        return EVENT_LOCATION
    except:
        await update.message.reply_text("❌ Неверный формат времени! Попробуйте еще раз.")
        return EVENT_END

async def process_event_location(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    date = context.user_data['event_date']
    start_time = context.user_data['event_start']
    end_time = context.user_data['event_end']
    location = update.message.text

    # Сохранение в Firestore
    db.collection('events').add({
        'user_id': user_id,
        'date': datetime.combine(date, start_time).isoformat(),
        'end_time': datetime.combine(date, end_time).isoformat(),
        'location': location,
        'timestamp': datetime.now().isoformat()
    })

    await update.message.reply_text("✅ Событие добавлено!")
    return ConversationHandler.END

# Просмотр текущих событий
async def current_events(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    now = datetime.now()
    two_days_later = now + timedelta(days=2)

    # Получение всех групп пользователя
    groups = db.collection('groups').where('members', 'array_contains', user_id).stream()
    group_names = [group.id for group in groups]

    if not group_names:
        await update.message.reply_text("❌ Вы не состоите ни в одной группе!")
        return

    # Получение событий
    events = db.collection('events').where('date', '>=', now.isoformat()).where('date', '<=', two_days_later.isoformat()).stream()

    response = "🍽️ Ближайшие события (2 дня):\n"
    events_found = False

    for event in events:
        event_data = event.to_dict()
        if event_data['user_id'] == user_id or any(group in group_names for group in event_data.get('groups', [])):
            events_found = True
            response += f"📅 {event_data['date']} - {event_data['end_time']}\n📍 {event_data['location']}\n\n"

    if not events_found:
        response = "🤷♂️ На ближайшие 2 дней записей нет."

    await update.message.reply_text(response)

# История событий
async def history(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    events = db.collection('events').order_by('timestamp').stream()

    response = "📜 История всех событий:\n"
    for event in events:
        event_data = event.to_dict()
        response += f"📅 {event_data['date']} - {event_data['end_time']}\n📍 {event_data['location']}\n\n"

    await update.message.reply_text(response)

def main() -> None:
    from token_for_tg import TOKEN_TG
    TOKEN = TOKEN_TG
    application = Application.builder().token(TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("current", current_events))
    application.add_handler(CommandHandler("history", history))

    # Создание группы
    conv_create = ConversationHandler(
        entry_points=[CommandHandler('create', create_group)],
        states={
            GROUP_NAME: [MessageHandler(filters.TEXT, process_group_name)],
            GROUP_PASSWORD: [MessageHandler(filters.TEXT, process_group_password)],
        },
        fallbacks=[]
    )

    # Присоединение к группе
    conv_join = ConversationHandler(
        entry_points=[CommandHandler('join', join_group)],
        states={
            JOIN_GROUP: [MessageHandler(filters.TEXT, process_join_group)],
            JOIN_PASSWORD: [MessageHandler(filters.TEXT, process_join_password)],
        },
        fallbacks=[]
    )

    # Добавление события
    conv_event = ConversationHandler(
        entry_points=[CommandHandler('addevent', add_event)],
        states={
            EVENT_DATE: [MessageHandler(filters.TEXT, process_event_date)],
            EVENT_START: [MessageHandler(filters.TEXT, process_event_start)],
            EVENT_END: [MessageHandler(filters.TEXT, process_event_end)],
            EVENT_LOCATION: [MessageHandler(filters.TEXT, process_event_location)],
        },
        fallbacks=[]
    )

    application.add_handler(conv_create)
    application.add_handler(conv_join)
    application.add_handler(conv_event)

    application.run_polling()

if __name__ == '__main__':
    main()