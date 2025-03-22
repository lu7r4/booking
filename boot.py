import logging
import asyncpg
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime

API_TOKEN = ''
DATABASE_URL = 'postgresql://test:test@localhost/test'


# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем экземпляр бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

async def create_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id SERIAL PRIMARY KEY,
            stand_id INT NOT NULL,  -- Допустим, stand_id обязательное поле
            stand_name VARCHAR(255) NULL,
            user_id INT NULL,
            username VARCHAR(255) NULL,
            task_title VARCHAR(255) NULL,
            start_time TIMESTAMP NULL,
            end_time TIMESTAMP NULL
        );
    ''')

async def add_user_to_db(user_id, username):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Логируем данные перед выполнением запроса
        logging.info(f"Adding user to database: user_id={user_id}, username={username}")
        
        await conn.execute('''
            INSERT INTO reservations (user_id, username, stand_id, stand_name, task_title, start_time, end_time)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (user_id) DO NOTHING;
        ''', user_id, username, None, None, None, None, None)

        # Проверяем добавление данных
        user_row = await conn.fetchrow('SELECT * FROM reservations WHERE user_id = $1', user_id)
        logging.info(f"User after insert: {user_row}")

    except Exception as e:
        logging.error(f"Ошибка при добавлении пользователя в базу: {e}")
    finally:
        await conn.close()

async def user_exists(user_id):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        row = await conn.fetchrow('SELECT * FROM reservations WHERE user_id = $1', user_id)
        return row is not None
    finally:
        await conn.close()

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else "no_username"

    if not await user_exists(user_id):
        await add_user_to_db(user_id, username)
        await message.reply("Ваши данные добавлены в базу данных.")
    else:
        await message.reply("Вы уже зарегистрированы в базе данных.")

async def on_startup(dp):
    await create_db()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup(dp))
    executor.start_polling(dp, skip_updates=True)
