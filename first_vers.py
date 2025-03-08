import os
import logging
from datetime import datetime
from aiohttp import web
import aiohttp_cors
import firebase_admin
from firebase_admin import credentials, firestore
import json
from json import dumps
from datetime import timedelta
# Настройка Firebase
firebase_config = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not firebase_config:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable not set!")

cred_dict = json.loads(firebase_config)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)



def format_event_time(event_data):
    # Предполагаем, что событие хранит время начала в поле 'start' и время окончания в поле 'end'
    start_str = event_data.get('start')
    end_str = event_data.get('end')
    if start_str:
        try:
            start_dt = datetime.fromisoformat(start_str)
            date_pretty = start_dt.strftime("%d.%m.%Y")  # например, "08.03.2025"
            time_pretty = start_dt.strftime("%H:%M")
        except Exception as e:
            date_pretty = "-"
            time_pretty = "-"
    else:
        date_pretty = "-"
        time_pretty = "-"

    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str)
            # Если нужно показать интервал времени
            time_pretty += f" - {end_dt.strftime('%H:%M')}"
        except Exception as e:
            time_pretty += " - -"
    else:
        time_pretty += " - -"

    return date_pretty, time_pretty


async def setup_http_server():
    app = web.Application()

    # Настройка CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*",
        )
    })

    # Эндпоинт: Получение групп пользователя
    async def get_groups(request):
        try:
            user_id = request.query.get('user_id')
            if not user_id:
                return web.json_response({'error': 'User ID required'}, status=400)

            groups = db.collection('groups').where('members', 'array_contains', int(user_id)).stream()
            result = [{'id': group.id, 'name': group.id} for group in groups]
            return web.json_response(result)

        except Exception as e:
            logger.error(f"Error getting groups: {str(e)}")
            return web.json_response({'error': 'Server error'}, status=500)

    # Эндпоинт: Создание группы
    async def create_group(request):
        try:
            data = await request.json()
            required_fields = ['user_id', 'name', 'password']

            if not all(field in data for field in required_fields):
                return web.json_response({'error': 'Missing required fields'}, status=400)

            group_name = data['name'].replace("/", "_")
            group_ref = db.collection('groups').document(group_name)

            if group_ref.get().exists:
                return web.json_response({'error': 'Group already exists'}, status=409)

            group_ref.set({
                'password': data['password'],
                'members': [int(data['user_id'])]
            })

            return web.json_response({'status': 'Group created'})

        except Exception as e:
            logger.error(f"Error creating group: {str(e)}")
            return web.json_response({'error': 'Server error'}, status=500)

    # Эндпоинт: Присоединение к группе
    async def join_group(request):
        try:
            data = await request.json()
            required_fields = ['user_id', 'name', 'password']

            if not all(field in data for field in required_fields):
                return web.json_response({'error': 'Missing required fields'}, status=400)

            group_ref = db.collection('groups').document(data['name'])
            group = group_ref.get()

            if not group.exists:
                return web.json_response({'error': 'Group not found'}, status=404)

            if group.to_dict().get('password') != data['password']:
                return web.json_response({'error': 'Invalid password'}, status=403)

            group_ref.update({
                'members': firestore.ArrayUnion([int(data['user_id'])])
            })

            return web.json_response({'status': 'Joined group'})

        except Exception as e:
            logger.error(f"Error joining group: {str(e)}")
            return web.json_response({'error': 'Server error'}, status=500)

    # Эндпоинт: Создание события
    async def create_event(request):
        try:
            data = await request.json()
            required_fields = ['user_id', 'group', 'start', 'end', 'location']

            if not all(field in data for field in required_fields):
                return web.json_response({'error': 'Missing required fields'}, status=400)

            group_ref = db.collection('groups').document(data['group'])
            if not group_ref.get().exists:
                return web.json_response({'error': 'Group not found'}, status=404)

            event_data = {
                'user_id': int(data['user_id']),
                'start': data['start'],  # например, "2025-03-08T13:00:00"
                'end': data['end'],  # например, "2025-03-08T15:00:00"
                'location': data['location'],
                'timestamp': datetime.now().isoformat()
            }

            group_ref.collection('events').add(event_data)
            return web.json_response({'status': 'Event created'})

        except Exception as e:
            logger.error(f"Error creating event: {str(e)}")
            return web.json_response({'error': 'Server error'}, status=500)

    # Эндпоинт: Получение событий
    async def get_events(request):
        try:
            group_name = request.query.get('group')
            time_filter = request.query.get('filter', 'current')

            if not group_name:
                return web.json_response({'error': 'Group name required'}, status=400)

            events_ref = db.collection('groups').document(group_name).collection('events')

            if time_filter == 'history':
                # Для истории можно сортировать по времени создания или по start
                events = events_ref.order_by('timestamp').stream()
            else:  # current – ближайшие 2 дня
                now = datetime.now()
                two_days_later = now + timedelta(days=2)
                now_iso = now.isoformat()
                two_days_later_iso = two_days_later.isoformat()
                events = events_ref \
                    .where('start', '>=', now_iso) \
                    .where('start', '<=', two_days_later_iso) \
                    .order_by('start') \
                    .stream()

            result = []
            for event in events:
                event_data = event.to_dict()
                event_data['id'] = event.id

                # Форматирование даты и времени для красивого вывода
                date_pretty, time_pretty = format_event_time(event_data)
                event_data['date'] = date_pretty  # перезаписываем поле date
                event_data['time'] = time_pretty  # перезаписываем поле time

                result.append(event_data)

            return web.json_response(result)

        except Exception as e:
            logger.error(f"Error getting events: {str(e)}")
            return web.json_response({'error': 'Server error'}, status=500)

    # Регистрация эндпоинтов
    routes = [
        ('/get_groups', 'GET', get_groups),
        ('/create_group', 'POST', create_group),
        ('/join_group', 'POST', join_group),
        ('/create_event', 'POST', create_event),
        ('/get_events', 'GET', get_events)
    ]

    for path, method, handler in routes:
        resource = cors.add(app.router.add_resource(path))
        cors.add(resource.add_route(method, handler))

    return app


async def main():
    # Настройка и запуск сервера
    app = await setup_http_server()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logger.info("Server started at http://0.0.0.0:8080")

    # Бесконечное ожидание
    while True:
        await asyncio.sleep(3600)


if __name__ == '__main__':
    import asyncio

    asyncio.run(main())