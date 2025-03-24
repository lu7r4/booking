from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
import asyncpg
import logging
import asyncio
import datetime
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


API_TOKEN = ''
DATABASE_URL = 'postgresql://test:test@localhost/test'


# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создаем экземпляр бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class BookingStates(StatesGroup):
    waiting_for_stand_selection = State()  # Для выбора стенда (если планируется)
    waiting_for_days = State()
    waiting_for_stand_name = State()
    waiting_for_task_title = State()

# Функция для отправки пользователям доступных стендов
async def send_stands(message: types.Message):
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        stands = await conn.fetch('SELECT stand_id, stand_name FROM reservations WHERE end_time IS NULL ORDER BY stand_id')

        logger.info(f"Найденные стенды в базе данных: {stands}")

        if stands:
            keyboard = types.InlineKeyboardMarkup()
            for stand in stands:
                # Важно сохранять stand_name в callback_data или в состоянии
                button = types.InlineKeyboardButton(
                    text=str(stand['stand_name']),
                    callback_data=f"book_stand_{stand['stand_id']}_{stand['stand_name']}"  # Добавляем stand_name
                )
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
async def process_stand_selection(callback_query: types.CallbackQuery):
    data_parts = callback_query.data.split('_')
    stand_id = int(data_parts[2])  # Получаем stand_id
    stand_name = data_parts[3]  # Получаем stand_name

    # Сохраняем stand_id и stand_name в состоянии для следующего этапа
    await BookingStates.waiting_for_task_title.set()
    await callback_query.answer()
    await callback_query.message.answer(f"Вы выбрали стенд '{stand_name}'. Теперь введите название задачи в JIRA:")
    
    # Сохраняем данные в контексте состояния
    await dp.current_state(user=callback_query.from_user.id).update_data(stand_id=stand_id, stand_name=stand_name)

@dp.message_handler(state=BookingStates.waiting_for_task_title)
async def process_task_title_input(message: types.Message, state: FSMContext):
    task_title = message.text
    
    # Получаем данные сохраненные в контексте
    data = await state.get_data()
    stand_id = data.get("stand_id")

    # Переходим к вводу дней
    await BookingStates.waiting_for_days.set()
    await message.answer(f"Вы ввели название задачи: '{task_title}'. Введите количество дней для бронирования:")
    
    # Сохраняем название задачи в контексте состояния
    await state.update_data(task_title=task_title)

def get_day_form(days):
    if 11 <= days % 100 <= 14:
        return 'дней'
    elif days % 10 == 1:
        return 'день'
    elif 2 <= days % 10 <= 4:
        return 'дня'
    else:
        return 'дней'

@dp.message_handler(state=BookingStates.waiting_for_days)
async def process_days_input(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else "no_username"

    # Получаем все данные, сохраненные в контексте
    data = await state.get_data()
    stand_id = data.get("stand_id")
    stand_name = data.get("stand_name")  # Извлекаем stand_name
    task_title = data.get("task_title")
    
    try:
        days = int(message.text)  # Пробуем преобразовать ввод в целое число
        end_time = datetime.datetime.now() + datetime.timedelta(days=days)

        # Отправляем сообщение с подтверждением
        day_form = get_day_form(days)
        await message.answer(f"Вы хотите забронировать стенд '{stand_name}' на {days} {day_form} до {end_time.strftime('%H:%M')}?", 
                             reply_markup=confirmation_keyboard())
        
        # Сохраняем данные о бронировании в контексте
        await state.update_data(days=days, end_time=end_time)
        
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число дней.")  # Обрабатываем нечисловой ввод

def confirmation_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    confirm_button = types.InlineKeyboardButton(text="Подтвердить", callback_data="confirm_booking")
    cancel_button = types.InlineKeyboardButton(text="Отмена", callback_data="cancel_booking")
    keyboard.add(confirm_button, cancel_button)
    return keyboard

@dp.callback_query_handler(lambda c: c.data == 'confirm_booking', state=BookingStates.waiting_for_days)
async def confirm_booking(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username if callback_query.from_user.username else "no_username"

    # Получаем данные из состояния
    data = await state.get_data()
    stand_id = data.get("stand_id")
    stand_name = data.get("stand_name")
    task_title = data.get("task_title")
    days = data.get("days")
    end_time = data.get("end_time")

    # Производим запись в БД
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Бронирование стенда
        await conn.execute('''
            INSERT INTO reservations (stand_id, user_id, username, task_title, end_time)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (stand_id) 
            DO UPDATE SET user_id = $2, username = $3, task_title = $4, end_time = $5;
        ''', stand_id, user_id, username, task_title, end_time)

        day_form = get_day_form(days)
        # Отправляем оповещение в чат
        await bot.send_message(callback_query.from_user.id, 
                                f"Стенд '{stand_name}' успешно забронирован на {days} {day_form} до {end_time.strftime('%H:%M')}.")
        logger.info(f"Стенд '{stand_name}' с ID '{stand_id}' успешно забронирован на {days} {day_form} для пользователя {username}.")
    except Exception as e:
        logger.error(f"Ошибка при бронировании стенда: {e}, "
                     f"stand_id: {stand_id}, user_id: {user_id}, "
                     f"username: '{username}', task_title: '{task_title}', "
                     f"end_time: '{end_time}'")
        await bot.send_message(callback_query.from_user.id, 
                               "Произошла ошибка при бронировании стенда. Попробуйте еще раз.")
    finally:
        await conn.close()
        logger.info("Соединение с базой данных закрыто.")
        await state.finish()  # Завершаем состояние

@dp.callback_query_handler(lambda c: c.data == 'cancel_booking', state=BookingStates.waiting_for_days)
async def cancel_booking(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.send_message(callback_query.from_user.id, "Бронирование отменено.")
    await state.finish()  # Завершаем состояние

def start_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    book_stand_button = KeyboardButton('Забронировать стенд')
    some_other_button = KeyboardButton('Другой вариант')  # Здесь пока просто текст
    keyboard.add(book_stand_button, some_other_button)
    return keyboard

@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=start_keyboard())

@dp.message_handler(lambda message: message.text == 'Забронировать стенд')
async def book_stand(message: types.Message):
    await send_stands(message)  # Здесь предполагается, что это ваша функция, начинающая процесс бронирования

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
