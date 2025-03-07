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
import json
#для коммита
# Настройка Firebase
firebase_config = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not firebase_config:
    raise ValueError("Переменная окружения GOOGLE_APPLICATION_CREDENTIALS не задана!")

cred_dict = json.loads(firebase_config)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
GROUP_NAME, GROUP_PASSWORD, JOIN_GROUP, JOIN_PASSWORD, \
    EVENT_DATE, EVENT_START, EVENT_END, EVENT_LOCATION, \
    SELECT_GROUP, SELECT_GROUP_CURRENT = range(10)


# Команда /start
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "🍴 Бот для организации совместных обедов!\n"
        "Создать группу: /create\n"
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

    group_name = group_name.replace("/", "_")

    try:
        db.collection('groups').document(group_name).set({
            'password': password,
            'members': [user_id]
        })
        await update.message.reply_text(f"✅ Группа '{group_name}' создана!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

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

    if group.to_dict().get('password') != password:
        await update.message.reply_text("❌ Неверный пароль!")
        return ConversationHandler.END

    group_ref.update({"members": firestore.ArrayUnion([user_id])})
    await update.message.reply_text(f"✅ Вы присоединились к группе '{group_name}'!")
    return ConversationHandler.END


# Добавление события
async def add_event(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    groups = db.collection('groups').where('members', 'array_contains', user_id).stream()
    group_names = [group.id for group in groups]

    if not group_names:
        await update.message.reply_text("❌ Вы не состоите ни в одной группе!")
        return ConversationHandler.END

    groups_str = "\n".join([f"{i + 1}. {name}" for i, name in enumerate(group_names)])
    await update.message.reply_text(f"Выберите группу:\n{groups_str}")
    context.user_data['available_groups'] = group_names
    return SELECT_GROUP


async def process_group_selection(update: Update, context: CallbackContext) -> int:
    try:
        selected = int(update.message.text) - 1
        group_names = context.user_data['available_groups']
        selected_group = group_names[selected]
        context.user_data['selected_group'] = selected_group
        await update.message.reply_text("Введите дату (например, 2023-10-10):")
        return EVENT_DATE
    except:
        await update.message.reply_text("❌ Неверный выбор. Попробуйте еще раз.")
        return SELECT_GROUP


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
    username = update.message.from_user.username or "Anonymous"
    date = context.user_data['event_date']
    start_time = context.user_data['event_start']
    end_time = context.user_data['event_end']
    location = update.message.text
    selected_group = context.user_data['selected_group']

    group_ref = db.collection('groups').document(selected_group)
    group_ref.collection('events').add({
        'user_id': user_id,
        'username': username,
        'date': datetime.combine(date, start_time).isoformat(),
        'end_time': datetime.combine(date, end_time).isoformat(),
        'location': location,
        'timestamp': datetime.now().isoformat()
    })

    await update.message.reply_text("✅ Событие добавлено!")
    return ConversationHandler.END


# Просмотр текущих событий
async def current_events(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    groups = db.collection('groups').where('members', 'array_contains', user_id).stream()
    group_names = [group.id for group in groups]

    if not group_names:
        await update.message.reply_text("❌ Вы не состоите ни в одной группе!")
        return ConversationHandler.END

    groups_str = "\n".join([f"{i + 1}. {name}" for i, name in enumerate(group_names)])
    await update.message.reply_text(f"Выберите группу для просмотра событий:\n{groups_str}")
    context.user_data['available_groups'] = group_names
    return SELECT_GROUP_CURRENT


async def process_group_current(update: Update, context: CallbackContext) -> int:
    try:
        selected = int(update.message.text) - 1
        group_names = context.user_data['available_groups']
        selected_group = group_names[selected]

        now = datetime.now()
        two_days_later = now + timedelta(days=2)

        events_ref = db.collection('groups').document(selected_group).collection('events')
        events = events_ref.where('date', '<=', two_days_later.isoformat()).order_by('date').stream()

        response = f"📅 События для группы '{selected_group}' в ближайшие 2 дня:\n"
        for event in events:
            data = event.to_dict()
            start_dt = datetime.fromisoformat(data['date'])
            end_dt = datetime.fromisoformat(data['end_time'])
            creator = data.get('username', 'Неизвестный')
            response += (
                f"⏰ {start_dt.strftime('%d.%m %H:%M')} - {end_dt.strftime('%H:%M')}\n"
                f"📍 {data['location']}\n"
                f"👤 Создатель: @{creator}\n\n"
            )

        if not response.strip():
            response = "Нет событий в выбранной группе."
        await update.message.reply_text(response)
    except:
        await update.message.reply_text("❌ Ошибка. Попробуйте еще раз.")
        return SELECT_GROUP_CURRENT

    return ConversationHandler.END


# История событий
async def history(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    groups = db.collection('groups').where('members', 'array_contains', user_id).stream()
    group_names = [group.id for group in groups]

    if not group_names:
        await update.message.reply_text("❌ Вы не состоите ни в одной группе!")
        return ConversationHandler.END

    groups_str = "\n".join([f"{i + 1}. {name}" for i, name in enumerate(group_names)])
    await update.message.reply_text(f"Выберите группу для просмотра истории:\n{groups_str}")
    context.user_data['available_groups'] = group_names
    return SELECT_GROUP_CURRENT


async def process_group_history(update: Update, context: CallbackContext) -> int:
    try:
        selected = int(update.message.text) - 1
        group_names = context.user_data['available_groups']
        selected_group = group_names[selected]

        events_ref = db.collection('groups').document(selected_group).collection('events')
        events = events_ref.order_by('timestamp').stream()

        response = f"📜 История группы '{selected_group}':\n"
        for event in events:
            data = event.to_dict()
            start_dt = datetime.fromisoformat(data['date'])
            end_dt = datetime.fromisoformat(data['end_time'])
            creator = data.get('username', 'Неизвестный')
            response += (
                f"📅 {start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}\n"
                f"📍 {data['location']}\n"
                f"👤 Создатель: @{creator}\n\n"
            )

        if not response.strip():
            response = "Нет событий в выбранной группе."
        await update.message.reply_text(response)
    except:
        await update.message.reply_text("❌ Ошибка. Попробуйте еще раз.")
        return SELECT_GROUP_CURRENT

    return ConversationHandler.END


def main() -> None:
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        raise ValueError("Переменная окружения TELEGRAM_TOKEN не задана!")

    application = Application.builder().token(TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))

    # Создание группы
    conv_create = ConversationHandler(
        entry_points=[CommandHandler('create', create_group)],
        states={
            GROUP_NAME: [MessageHandler(filters.TEXT, process_group_name)],
            GROUP_PASSWORD: [MessageHandler(filters.TEXT, process_group_password)],
        },
        fallbacks=[],
    )

    # Присоединение к группе
    conv_join = ConversationHandler(
        entry_points=[CommandHandler('join', join_group)],
        states={
            JOIN_GROUP: [MessageHandler(filters.TEXT, process_join_group)],
            JOIN_PASSWORD: [MessageHandler(filters.TEXT, process_join_password)],
        },
        fallbacks=[],
    )

    # Добавление события
    conv_event = ConversationHandler(
        entry_points=[CommandHandler('addevent', add_event)],
        states={
            SELECT_GROUP: [MessageHandler(filters.TEXT, process_group_selection)],
            EVENT_DATE: [MessageHandler(filters.TEXT, process_event_date)],
            EVENT_START: [MessageHandler(filters.TEXT, process_event_start)],
            EVENT_END: [MessageHandler(filters.TEXT, process_event_end)],
            EVENT_LOCATION: [MessageHandler(filters.TEXT, process_event_location)],
        },
        fallbacks=[],
    )

    # Текущие события
    conv_current = ConversationHandler(
        entry_points=[CommandHandler('current', current_events)],
        states={
            SELECT_GROUP_CURRENT: [MessageHandler(filters.TEXT, process_group_current)],
        },
        fallbacks=[],
    )

    # История событий
    conv_history = ConversationHandler(
        entry_points=[CommandHandler('history', history)],
        states={
            SELECT_GROUP_CURRENT: [MessageHandler(filters.TEXT, process_group_history)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_create)
    application.add_handler(conv_join)
    application.add_handler(conv_event)
    application.add_handler(conv_current)
    application.add_handler(conv_history)

    application.run_polling()


if __name__ == '__main__':
    main()