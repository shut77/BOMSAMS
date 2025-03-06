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

# Настройка Firebase
firebase_config = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not firebase_config:
    raise ValueError("Переменная окружения GOOGLE_APPLICATION_CREDENTIALS не задана!")
cred_dict = json.loads(firebase_config)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Настройка логов
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(
    GROUP_NAME, GROUP_PASSWORD, JOIN_GROUP, JOIN_PASSWORD,
    EVENT_GROUP, EVENT_DATE, EVENT_START, EVENT_END, EVENT_LOCATION,
    CURRENT_CHOOSE_GROUP
) = range(10)

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

# Создание группы (остается без изменений)
# ... [Остальные функции создания и присоединения к группе без изменений] ...

# Добавление события (обновлено для выбора группы)
async def add_event(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    groups = db.collection('groups').where('members', 'array_contains', user_id).stream()
    group_names = [group.id for group in groups]

    if not group_names:
        await update.message.reply_text("❌ Вы не состоите ни в одной группе! Сначала создайте или присоединитесь к группе.")
        return ConversationHandler.END

    context.user_data['user_groups'] = group_names
    group_list = "\n".join(group_names)
    await update.message.reply_text(f"Выберите группу для события:\n{group_list}")
    return EVENT_GROUP

async def process_event_group(update: Update, context: CallbackContext) -> int:
    selected_group = update.message.text
    user_groups = context.user_data.get('user_groups', [])

    if selected_group not in user_groups:
        await update.message.reply_text("❌ Вы не состоите в этой группе. Выберите из списка.")
        return EVENT_GROUP

    context.user_data['event_group'] = selected_group
    await update.message.reply_text("Введите дату (например, 2023-10-10):")
    return EVENT_DATE

# ... [Обработчики даты, времени и места остаются без изменений] ...

async def process_event_location(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    date = context.user_data['event_date']
    start_time = context.user_data['event_start']
    end_time = context.user_data['event_end']
    location = update.message.text
    event_group = context.user_data['event_group']

    db.collection('events').add({
        'user_id': user_id,
        'group': event_group,
        'date': datetime.combine(date, start_time).isoformat(),
        'end_time': datetime.combine(date, end_time).isoformat(),
        'location': location,
        'timestamp': datetime.now().isoformat()
    })

    await update.message.reply_text("✅ Событие добавлено!")
    return ConversationHandler.END

# Просмотр текущих событий (обновлено)
async def current_events_start(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    groups = db.collection('groups').where('members', 'array_contains', user_id).stream()
    group_names = [group.id for group in groups]

    if not group_names:
        await update.message.reply_text("❌ Вы не состоите ни в одной группе!")
        return ConversationHandler.END

    context.user_data['current_groups'] = group_names
    group_list = "\n".join(group_names)
    await update.message.reply_text(f"Выберите группу:\n{group_list}")
    return CURRENT_CHOOSE_GROUP

async def process_current_group(update: Update, context: CallbackContext) -> int:
    selected_group = update.message.text
    current_groups = context.user_data.get('current_groups', [])

    if selected_group not in current_groups:
        await update.message.reply_text("❌ Группа не найдена! Выберите из списка.")
        return CURRENT_CHOOSE_GROUP

    now = datetime.now()
    two_days_later = now + timedelta(days=2)
    events = db.collection('events').where('group', '==', selected_group)\
                                      .where('date', '>=', now.isoformat())\
                                      .where('date', '<=', two_days_later.isoformat())\
                                      .stream()

    response = f"🍽️ События в группе '{selected_group}':\n"
    events_found = False

    for event in events:
        event_data = event.to_dict()
        events_found = True
        creator_link = f"tg://user?id={event_data['user_id']}"
        start_time = parser.parse(event_data['date']).strftime("%d.%m.%Y %H:%M")
        end_time = parser.parse(event_data['end_time']).strftime("%H:%M")
        response += (
            f"📅 *{start_time}-{end_time}*\n"
            f"📍 {event_data['location']}\n"
            f"👤 [Создатель]({creator_link})\n\n"
        )

    if not events_found:
        response = "🤷♂️ На ближайшие 2 дня событий нет."

    await update.message.reply_text(response, parse_mode='Markdown')
    return ConversationHandler.END

def main() -> None:
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    application = Application.builder().token(TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("history", history))

    # ... [Остальные обработчики создания/присоединения к группе] ...

    # Обработчик текущих событий
    conv_current = ConversationHandler(
        entry_points=[CommandHandler('current', current_events_start)],
        states={CURRENT_CHOOSE_GROUP: [MessageHandler(filters.TEXT, process_current_group)]},
        fallbacks=[]
    )
    application.add_handler(conv_current)

    application.run_polling()

if __name__ == '__main__':
    main()