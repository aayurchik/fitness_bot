import aiohttp
import matplotlib.pyplot as plt
from io import BytesIO
from config import WEATHER_API_KEY
from difflib import get_close_matches

# Получение температуры из OpenWeather

async def get_temperature(city: str) -> float | None:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": WEATHER_API_KEY, "units": "metric"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data["main"]["temp"]
    except Exception:
        return None


# Норма воды: 30 мл / кг
# + 500 мл за каждые 30 мин активности
# + поправка на жару

def calc_water(weight: float, activity: int, temp: float | None) -> float:
    base = weight * 0.03
    activity_part = (activity / 30) * 0.5
    heat_part = 0
    if temp is not None and temp > 25:
        heat_part = (temp - 25) * 0.02
    return round(base + activity_part + heat_part, 2)


# Норма калорий
def calc_calories(weight: float, height: float, age: int, activity: int, sex: str) -> int:
    if sex == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    activity_part = min(activity / 30 * 50, 400)
    return int(bmr + activity_part)


# График для прогресса по воде
def water_plot(drunk_ml: float, goal_ml: float):
    left_ml = max(goal_ml - drunk_ml, 0)
    plt.figure(figsize=(7, 4))
    plt.bar(["Выпито", "Осталось"], [drunk_ml/1000, left_ml/1000], width=0.5)
    plt.title("Прогресс по воде")
    plt.ylabel("Литры")
    plt.ylim(0, goal_ml/1000 * 1.2)
    plt.grid(axis="y", alpha=0.3)
    plt.text(0, drunk_ml/1000 + 0.05, f"{drunk_ml/1000:.1f} л", ha="center")
    plt.text(1, left_ml/1000 + 0.05, f"{left_ml/1000:.1f} л", ha="center")
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)
    percent = (drunk_ml / goal_ml) * 100 if goal_ml else 0
    return buf, percent


# Локальной сет продуктов с калорийностью

LOCAL_FOODS = {
    "яблоко": 52, "банан": 89, "груша": 57, "апельсин": 47, "мандарин": 53,
    "виноград": 72, "персик": 39, "картофель": 77, "рис": 130, "гречка": 110,
    "макароны": 131, "овсянка": 68, "хлеб": 265, "белый хлеб": 266,
    "курица": 165, "говядина": 250, "свинина": 260, "рыба": 140,
    "яйцо": 155, "сыр": 402, "творог": 121, "молоко": 60, "йогурт": 59,
    "кефир": 53, "шоколад": 546, "печенье": 480, "пицца": 266, "бургер": 295,
    "каша": 110, "салат": 25, "огурец": 16, "помидор": 18, "морковь": 41}

# Получение калорийности
def get_food_info(product_name: str):
    query = product_name.lower().strip()
    if query in LOCAL_FOODS:
        return True, LOCAL_FOODS[query], query

    matches = get_close_matches(query, LOCAL_FOODS.keys(), n=1, cutoff=0.6)
    if matches:
        key = matches[0]
        return True, LOCAL_FOODS[key], key

    return False, 0, ""

# Прогресс по калориям 
def calories_plot(consumed: float, goal: float):
    left = max(goal - consumed, 0)
    plt.figure(figsize=(7, 4))
    plt.bar(["Съедено", "Осталось"], [consumed, left], width=0.5, color=["green", "orange"])
    plt.ylim(0, goal * 1.2)
    plt.ylabel("Ккал")
    plt.title("Прогресс по калориям")
    plt.grid(axis="y", alpha=0.3)
    plt.text(0, consumed + goal*0.02, f"{consumed:.0f} ккал", ha="center")
    plt.text(1, left + goal*0.02, f"{left:.0f} ккал", ha="center")
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)
    percent = (consumed / goal) * 100 if goal else 0
    return buf, percent

# Тренировки: калории в минуту
WORKOUT_CALORIES = {
    "бег": 10,   
    "ходьба": 4,  
    "велосипед": 8, 
    "плавание": 9,  
    "йога": 3, 
    "тренажер": 6,}

# рекомендации
def simple_recommend(calories_left):
    recs = []
    if calories_left > 0:
        recs.append(f"Можно съесть еще {calories_left:.0f} ккал")
        top_5 = list(LOCAL_FOODS.items())[:5]  # берем первые 5 продуктов
        for food_name, calories in top_5:
            if calories > 0:
                grams = (calories_left / calories) * 100
                recs.append(f"• {food_name}: {grams:.0f}г")
    elif calories_left < 0:
        # Переели нужно сжечь
        excess = abs(calories_left)
        recs.append(f"Переели на {excess:.0f} ккал")
        # Используем существующие тренировки из WORKOUT_CALORIES
        for workout, cal_per_min in WORKOUT_CALORIES.items():
            if cal_per_min > 0:
                minutes = excess / cal_per_min
                recs.append(f"• {workout}: {minutes:.0f} мин")
                break  # только одну тренировку показываем
    return recs