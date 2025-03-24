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
logger = logging.getLogger(__name__)

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

# Функция для отправки пользователям доступных стендов
async def send_stands(message: types.Message):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        stands = await conn.fetch('SELECT stand_id FROM reservations WHERE end_time IS NULL ORDER BY stand_id')

        logger.info(f"Найденные стенды в базе данных: {stands}")

        if stands:
            keyboard = types.InlineKeyboardMarkup()
            for stand in stands:
                # Используем только stand_id в качестве текста кнопки
                button = types.InlineKeyboardButton(text=str(stand['stand_id']), callback_data=f"book_stand_{stand['stand_id']}")
                keyboard.add(button)

            await message.reply("Выберите стенд:", reply_markup=keyboard)
            logger.info("Кнопки стендов успешно отправлены пользователю.")
        else:
            await message.reply("Нет доступных стендов.")
            logger.info("Нет доступных стендов для бронирования.")
    except Exception as e:
        logger.error(f"Ошибка при получении стендов: {e}")
    finally:
        await conn.close()
        logger.info("Соединение с базой данных закрыто.")


@dp.callback_query_handler(lambda c: c.data.startswith('book_stand_'))
async def process_stand_booking(callback_query: types.CallbackQuery):
    stand_id = int(callback_query.data.split('_')[2])
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username if callback_query.from_user.username else "no_username"
    end_time = datetime.datetime.now() + datetime.timedelta(days=3)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Используем INSERT ... ON CONFLICT для добавления или обновления записи по стенду
        await conn.execute('''
            INSERT INTO reservations (stand_id, user_id, username, end_time)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (stand_id) 
            DO UPDATE SET user_id = $2, username = $3, end_time = $4;
        ''', stand_id, user_id, username, end_time)
        
        await callback_query.answer(f"Вы успешно забронировали стенд {stand_id}!")
        
    except Exception as e:
        await callback_query.answer(f"Ошибка при бронировании: {e}")
    finally:
        await conn.close()

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await send_stands(message)

async def on_startup(dp):
    # Здесь можно добавить код для инициализации базы данных, если это необходимо.
    logging.info("Bot is ready!")

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(on_startup(dp))
    executor.start_polling(dp, skip_updates=True)
