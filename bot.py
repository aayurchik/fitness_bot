import asyncio
import os 
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from config import BOT_TOKEN
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
import logging
from aiohttp import web 
from utils import get_temperature, calc_water, calc_calories, water_plot, get_food_info, WORKOUT_CALORIES, calories_plot, simple_recommend

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if hasattr(event, "text") and event.text:
            logging.info(f"USER {event.from_user.id}: {event.text}")
        return await handler(event, data)
dp.message.middleware(LoggingMiddleware())

users = {}

# States
class ProfileForm(StatesGroup):
    weight = State()
    height = State()
    age = State()
    sex = State()
    activity = State()
    city = State()

class WaterLogging(StatesGroup):
    waiting_for_amount = State()

class FoodLogging(StatesGroup):
    waiting_for_food_name = State()
    waiting_for_food_amount = State()


# FSM для тренировок
class WorkoutLogging(StatesGroup):
    waiting_for_type = State()
    waiting_for_minutes = State()
    waiting_for_custom_calories = State()

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Запустите команду /set_profile\n\n"
        "Доступные команды:\n"
        "/set_profile - настройка профиля\n"
        "/log_water - записать воду\n"
        "/log_food - записать еду\n"
        "/log_workout - записать тренировку\n"
        "/water_graph - график прогресса по воде\n"
        "/check_progress - общий прогресс\n"
        "/recommend - рекомендации") 

@dp.message(Command("set_profile"))
async def set_profile(message: Message, state: FSMContext):
    await state.set_state(ProfileForm.weight)
    await message.answer("Введите вес (в кг):")


@dp.message(ProfileForm.weight)
async def process_weight(message: Message, state: FSMContext):
    await state.update_data(weight=float(message.text))
    await state.set_state(ProfileForm.height)
    await message.answer("Введите рост (в см):")


@dp.message(ProfileForm.height)
async def process_height(message: Message, state: FSMContext):
    await state.update_data(height=float(message.text))
    await state.set_state(ProfileForm.age)
    await message.answer("Введите возраст:")

@dp.message(ProfileForm.age)
async def process_age(message: Message, state: FSMContext):
    await state.update_data(age=int(message.text))
    await state.set_state(ProfileForm.sex)
    await message.answer("Укажите пол (male / female):")

@dp.message(ProfileForm.sex)
async def process_sex(message: Message, state: FSMContext):
    sex = message.text.lower()
    if sex not in ("male", "female"):
        await message.answer("Введите: male или female")
        return
    await state.update_data(sex=sex)
    await state.set_state(ProfileForm.activity)
    await message.answer("Сколько минут активности в день?")

@dp.message(ProfileForm.activity)
async def process_activity(message: Message, state: FSMContext):
    await state.update_data(activity=int(message.text))
    await state.set_state(ProfileForm.city)
    await message.answer("Введите город:")

@dp.message(ProfileForm.city)
async def process_city(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    temp = await get_temperature(message.text)
    water_goal = calc_water(data["weight"], data["activity"], temp)
    calorie_goal = calc_calories(
        data["weight"],
        data["height"],
        data["age"],
        data["activity"],
        data["sex"],)
    if temp is None:
        temp_text = "город не найден. без учета температуры."
    else:
        temp_text = f"{temp}°C"

    users[user_id] = {
        **data,
        "city": message.text,
        "water_goal": water_goal,
        "calorie_goal": calorie_goal,
        "logged_water": 0,
        "logged_calories": 0,
        "burned_calories": 0,
        "water_history": [], 
        "workout_minutes": 0,}

    await state.clear()

    await message.answer(
        f"Температура: {temp_text}\n"
        f"Норма воды: {water_goal} л\n"
        f"Норма калорий: {calorie_goal} ккал")

# Команда /log_water бот спрашивает количество
@dp.message(Command("log_water"))
async def start_log_water(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("установите профиль /set_profile")
        return
    await state.set_state(WaterLogging.waiting_for_amount)
    await message.answer("Введите количество воды в мл:")

# Обработка ввода числа
@dp.message(WaterLogging.waiting_for_amount)
async def process_log_water(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите число в мл, например: 250")
        return
    users[user_id]["logged_water"] += amount
    users[user_id]["water_history"].append(amount)
    # Цель в мл
    goal_ml = users[user_id]["water_goal"] * 1000
    done_ml = users[user_id]["logged_water"]
    left_ml = max(goal_ml - done_ml, 0)
    await message.answer(
        f"Выпито: {done_ml:.0f} / {goal_ml:.0f} мл\n"
        f"Осталось: {left_ml:.0f} мл")
    await state.clear()


@dp.message(Command("water_graph"))
async def show_water_graph(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Сначала установите /set_profile")
        return
    user_data = users[user_id]
    drunk_ml = user_data["logged_water"]
    goal_ml = user_data["water_goal"] * 1000  # переводим литры в мл
    # Строим простой график
    buf, percent = water_plot(drunk_ml, goal_ml)
    # Отправляем график
    photo = BufferedInputFile(buf.getvalue(), filename="water_graph.png")
    # Текст прогресса
    left_ml = max(goal_ml - drunk_ml, 0)
    progress_text = ""
    if percent >= 100:
        progress_text = "Отлично! Вы выполнили норму!"
    elif percent >= 75:
        progress_text = "Почти у цели!"
    elif percent >= 50:
        progress_text = "Продолжайте в том же духе!"
    else:
        progress_text = "Еще есть что пить!"
    
    caption = (
        f"Прогресс по воде\n\n"
        f"Выпито: {drunk_ml:.0f} мл ({drunk_ml/1000:.1f} л)\n"
        f"Цель: {goal_ml:.0f} мл ({goal_ml/1000:.1f} л)\n"
        f"Осталось: {left_ml:.0f} мл ({left_ml/1000:.1f} л)\n"
        f"Выполнено: {percent:.1f}%\n\n"
        f"{progress_text}")
    
    await message.answer_photo(photo, caption=caption)

# обработчик
@dp.message(Command("log_food"))
async def start_log_food(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("установите профиль /set_profile")
        return
    await state.set_state(FoodLogging.waiting_for_food_name)
    await message.answer("Что съели?")

@dp.message(FoodLogging.waiting_for_food_name)
async def process_food_name(message: Message, state: FSMContext):
    product_name = message.text.strip()
    found, calories_per_100g, name = get_food_info(product_name)
    
    if not found:
        await message.answer(f"Не нашел '{product_name}'. Использую среднее: 100 ккал/100г")
        calories_per_100g = 100
        name = product_name
    
    await state.update_data(calories_per_100g=calories_per_100g, food_name=name)
    await state.set_state(FoodLogging.waiting_for_food_amount)
    await message.answer(f"{name} - {calories_per_100g} ккал/100г. Сколько грамм?")

# Логирование еды 

@dp.message(FoodLogging.waiting_for_food_amount)
async def process_food_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("установите /set_profile")
        await state.clear()
        return
    try:
        grams = float(message.text)
    except ValueError:
        await message.answer("Сколько грамм? Например: 120")
        return

    data = await state.get_data()
    calories_per_100g = data.get("calories_per_100g", 0)
    total_calories = grams / 100 * calories_per_100g
    users[user_id]["logged_calories"] += total_calories

    #  вывод прогресса 
    calorie_goal = users[user_id]["calorie_goal"]
    consumed = users[user_id]["logged_calories"]
    left = max(calorie_goal - consumed, 0)
    buf, percent = calories_plot(consumed, calorie_goal)

    # текст прогресса
    if percent >= 100:
        progress_text = "Вы достигли нормы калорий!"
    elif percent >= 75:
        progress_text = "Почти у цели :)"
    elif percent >= 50:
        progress_text = "Неплохо, продолжайте!"
    else:
        progress_text = "Еще есть место для еды!"

    from aiogram.types import BufferedInputFile
    photo = BufferedInputFile(buf.getvalue(), filename="calories_graph.png")
    caption = (
        f"Суммарно: {consumed:.0f} / {calorie_goal:.0f} ккал\n"
        f"Осталось: {left:.0f} ккал\n"
        f"Выполнено: {percent:.1f}%\n\n"
        f"{progress_text}")
    await message.answer_photo(photo, caption=caption)
    await state.clear()

# Логирование воркаута

@dp.message(Command("log_workout"))
async def start_log_workout(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Сначала /set_profile")
        return
    
    # Показываем доступные типы + другое
    workout_types = "бег, ходьба, велосипед, плавание, йога, тренажер, другое"
    await state.set_state(WorkoutLogging.waiting_for_type)
    await message.answer(f"Какой тип? Пропишите слово: {workout_types}")

#  Обрабатываем выбор типа тренировки
@dp.message(WorkoutLogging.waiting_for_type)
async def process_workout_type(message: Message, state: FSMContext):
    workout_type = message.text.strip().lower()
    # Сохраняем тип тренировки
    await state.update_data(workout_type=workout_type)
    await state.set_state(WorkoutLogging.waiting_for_minutes)
    # Спрашиваем время тренировки
    await message.answer(f"Сколько минут вы тренировались?")

# Обрабатываем ввод минут тренировки
@dp.message(WorkoutLogging.waiting_for_minutes)
async def process_workout_minutes(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        minutes = int(message.text)
        if minutes <= 0:
            await message.answer("Введите положительное число минут")
            return
    except:
        await message.answer("Введите число минут")
        return

    await state.update_data(minutes=minutes)

    # Получаем тип тренировки
    data = await state.get_data()
    workout_type = data.get("workout_type", "")

    # для пересчёта воды
    users[user_id]["workout_minutes"] += minutes
    base_activity = users[user_id]["activity"]
    total_activity_for_day = base_activity + users[user_id]["workout_minutes"]
    # Если "другое", спрашиваем калории
    if "другое" in workout_type:
        await state.set_state(WorkoutLogging.waiting_for_custom_calories)
        await message.answer("Сколько примерно калорий сожгли?")
        return
    # Для известных типов тренировки считаем калории
    calories_burned = WORKOUT_CALORIES.get(workout_type, None)
    if calories_burned is None:
        await state.set_state(WorkoutLogging.waiting_for_custom_calories)
        await message.answer("Не нашел этот тип. Сколько примерно калорий сожгли?")
        return
    calories_burned *= minutes
    users[user_id]["burned_calories"] += calories_burned

    # Пересчитываем норму воды с учётом тренировки
    temp = await get_temperature(users[user_id]["city"])
    users[user_id]["water_goal"] = calc_water(
        users[user_id]["weight"],
        total_activity_for_day,  # используем временную сумму
        temp)

    # Подготовка прогресса
    calorie_goal = users[user_id]["calorie_goal"]
    logged = users[user_id]["logged_calories"]
    burned = users[user_id]["burned_calories"]
    calories_left = max(calorie_goal - logged + burned, 0)
    water_goal_ml = users[user_id]["water_goal"] * 1000
    water_drunk_ml = users[user_id]["logged_water"]
    water_left_ml = max(water_goal_ml - water_drunk_ml, 0)
    water_percent = (water_drunk_ml / water_goal_ml * 100) if water_goal_ml > 0 else 0

    await message.answer(
        f"🏋️‍♂️ {workout_type} {minutes} мин = {calories_burned:.0f} ккал\n\n"
        f"Прогресс:\n"
        f"Калории осталось: {calories_left:.0f} ккал\n"
        f"Воды осталось: {water_left_ml:.0f} мл ({water_percent:.1f}%)\n"
        f"Норма воды обновлена: {users[user_id]['water_goal']:.1f} л")
    await state.clear()


# Обработка для другого типа
@dp.message(WorkoutLogging.waiting_for_custom_calories)
async def process_custom_calories(message: Message, state: FSMContext):
    user_id = message.from_user.id

    try:
        calories = float(message.text)
        if calories <= 0:
            await message.answer("Введите положительное число")
            return
    except:
        await message.answer("Введите число калорий")
        return

    data = await state.get_data()
    workout_type = data.get("workout_type", "другое")
    minutes = data.get("minutes", 0)

    # Добавляем калории к сожжённым
    users[user_id]["burned_calories"] += calories

    # Пересчитываем воду
    users[user_id]["workout_minutes"] += minutes
    base_activity = users[user_id]["activity"]
    total_activity_for_day = base_activity + users[user_id]["workout_minutes"]
    temp = await get_temperature(users[user_id]["city"])
    users[user_id]["water_goal"] = calc_water(
        users[user_id]["weight"],
        total_activity_for_day,  # учитываем только текущую тренировку временно
        temp)

    # Подготовка прогресса
    calorie_goal = users[user_id]["calorie_goal"]
    logged = users[user_id]["logged_calories"]
    burned = users[user_id]["burned_calories"]
    calories_left = max(calorie_goal - logged + burned, 0)
    water_goal_ml = users[user_id]["water_goal"] * 1000
    water_drunk_ml = users[user_id]["logged_water"]
    water_left_ml = max(water_goal_ml - water_drunk_ml, 0)
    water_percent = (water_drunk_ml / water_goal_ml * 100) if water_goal_ml > 0 else 0

    await message.answer(
        f"🏋️‍♂️ {workout_type} {minutes} мин = {calories:.0f} ккал\n\n"
        f"Прогресс:\n"
        f"Калории осталось: {calories_left:.0f} ккал\n"
        f"Воды осталось: {water_left_ml:.0f} мл ({water_percent:.1f}%)\n"
        f"Норма воды обновлена: {users[user_id]['water_goal']:.1f} л")
    await state.clear()


# Команда /check_progress
@dp.message(Command("check_progress"))
async def check_progress(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Установите /set_profile")
        return
    user_data = users[user_id]
    
    # Данные по воде
    water_drunk_ml = user_data["logged_water"]
    water_goal_ml = user_data["water_goal"] * 1000  # переводим литры в мл
    water_left_ml = max(water_goal_ml - water_drunk_ml, 0)
    water_percent = (water_drunk_ml / water_goal_ml * 100) if water_goal_ml > 0 else 0
    
    # Данные по калориям
    calories_consumed = user_data["logged_calories"]
    calories_goal = user_data["calorie_goal"]
    calories_burned = user_data["burned_calories"]
    
    # Калории осталось = норма - (потреблено - сожжено)
    calories_balance = calories_consumed - calories_burned
    calories_left_for_today = max(calories_goal - calories_balance, 0)
    
    # Процент от нормы (потреблено от цели)
    calories_percent = (calories_consumed / calories_goal * 100) if calories_goal > 0 else 0
    
    # Формируем прогресс-бары
    def create_progress_bar(percent, length=10):
        filled = int(length * min(percent, 100) / 100)
        return "[" + "▓" * filled + "░" * (length - filled) + "]"
    
    water_bar = create_progress_bar(water_percent)
    calories_bar = create_progress_bar(calories_percent)
    
    response = (
        "**Прогресс**\n\n"
        "**Вода:**\n"
        f"- Выпито: {water_drunk_ml:.0f} мл из {water_goal_ml:.0f} мл\n"
        f"- Осталось: {water_left_ml:.0f} мл\n\n"
        
        "**Калории:**\n"
        f"- Потреблено: {calories_consumed:.0f} ккал из {calories_goal:.0f} ккал\n"
        f"- Сожжено: {calories_burned:.0f} ккал\n"
        f"- Баланс: {calories_balance:.0f} ккал\n"
        f"- До цели осталось: {calories_left_for_today:.0f} ккал\n\n")
    
    # Добавляем прогресс-бары отдельно
    response += f"Вода: {water_bar} {water_percent:.1f}%\n"
    response += f"Калории: {calories_bar} {calories_percent:.1f}%\n\n"
    
    # Рекомендации
    if water_percent >= 100:
        response += "Норма воды выполнена!\n"
    elif water_percent < 50:
        response += "Выпейте еще воды!\n"
    
    if calories_balance > calories_goal:
        response += f"Превышение: {calories_balance - calories_goal:.0f} ккал\n"
    elif calories_left_for_today > 0:
        response += f"Можно съесть еще {calories_left_for_today:.0f} ккал\n"
    
    await message.answer(response, parse_mode="Markdown")

# Команда /recommend
@dp.message(Command("recommend"))
async def recommend(message: Message):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Установите /set_profile")
        return
    user_data = users[user_id]
    
    # Считаем остаток калорий
    calories_consumed = user_data["logged_calories"]
    calories_goal = user_data["calorie_goal"]
    calories_burned = user_data["burned_calories"]
    calories_balance = calories_consumed - calories_burned
    calories_left = calories_goal - calories_balance
    # Получаем рекомендации
    recs = simple_recommend(calories_left)
    # ответ
    response = "**Рекомендации**\n\n"
    if recs:
        for rec in recs:
            response += f"{rec}\n"
    else:
        response += "Вы в норме!"
    await message.answer(response)

# Фиктивный веб-сервер для Render
async def hello(request):
    return web.Response(text="Bot is alive!")

app = web.Application()
app.add_routes([web.get("/", hello)])

# порт берем из переменной Render
port = int(os.environ.get("PORT", 10000))

async def main():
    # запускаем бот и веб-сервер параллельно
    await asyncio.gather(
        dp.start_polling(bot),
        web._run_app(app, host="0.0.0.0", port=port))

if __name__ == "__main__":
    asyncio.run(main())
