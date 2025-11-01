import json
import math
import time
from flask import Flask, request, jsonify
from threading import Thread
from pyowm.owm import OWM
from pyowm.utils.config import get_default_config
import telebot
from rapidfuzz import process, fuzz
from deep_translator import GoogleTranslator
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
import os

# --- Настройки OpenWeatherMap ---
config_dict = get_default_config()
config_dict['language'] = 'ru'
owm = OWM('d4dc73858b6dcf1c20253897a9988e8b', config_dict)
mgr = owm.weather_manager()

# --- Настройки Telegram бота ---
bot = telebot.TeleBot('8238571358:AAHOly27dfnDFKDurqoRopehD2h6h2gH7Jc', parse_mode=None)

# --- Проверка наличия облегчённого списка городов ---
if not os.path.exists('city.list.small.json'):
    print("Создаю облегчённый список городов...")
    with open('city.list.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    reduced = []
    for c in data:
        entry = {'name': c['name']}
        if 'local_names' in c and 'ru' in c['local_names']:
            entry['local_names'] = {'ru': c['local_names']['ru']}
        reduced.append(entry)

    with open('city.list.small.json', 'w', encoding='utf-8') as f:
        json.dump(reduced, f, ensure_ascii=False)
    print("Готово: city.list.small.json создан.")

# --- Загрузка облегчённого списка ---
with open('city.list.small.json', 'r', encoding='utf-8') as f:
    city_data = json.load(f)

all_cities = set()
for c in city_data:
    all_cities.add(c['name'].lower())
    if 'local_names' in c and 'ru' in c['local_names']:
        all_cities.add(c['local_names']['ru'].lower())
all_cities = list(all_cities)

translator = GoogleTranslator(source='auto', target='en')
cache = {}

# --- Flask сервер для WebApp ---
app = Flask(__name__)

@app.route('/api/weather')
def api_weather():
    city = request.args.get('city', '')
    if not city:
        return jsonify({'text': 'Укажи город.'})
    try:
        observation = mgr.weather_at_place(city)
        w = observation.weather
        temp = round(w.temperature('celsius')['temp'])
        feels = round(w.temperature('celsius')['feels_like'])
        status = w.detailed_status
        text = f"{city.title()}: {status}, {temp}°C (ощущается как {feels}°C)"
    except Exception:
        text = "Не удалось получить данные о погоде."
    return jsonify({'text': text})


def run_flask():
    app.run(host='0.0.0.0', port=5000)


# --- Telegram хэндлеры ---
@bot.message_handler(commands=['start', 'help'])
def send_start(message):
    bot.send_message(message.chat.id, 'Напиши мне город и я скажу, какая там погода.\n'
                                      'Или нажми /weather, чтобы открыть приложение.')

@bot.message_handler(commands=['weather'])
def webapp_start(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    web_app = WebAppInfo(url="https://your-domain.com")  # заменишь на свой URL
    markup.add(KeyboardButton("Открыть приложение", web_app=web_app))
    bot.send_message(message.chat.id, "Нажми, чтобы открыть приложение:", reply_markup=markup)


@bot.message_handler(content_types=['text'])
def send_echo(message):
    place = message.text.strip().lower()

    try:
        translated_place = translator.translate(place) or place
    except Exception:
        translated_place = place

    match, score, _ = process.extractOne(translated_place, all_cities, scorer=fuzz.WRatio)

    if score < 80:
        suggestions = [m[0].title() for m in process.extract(translated_place, all_cities, limit=3) if m[1] > 50]
        if suggestions:
            text = "Не нашел такой город. Может, ты имел в виду: " + ", ".join(suggestions) + "?"
        else:
            text = 'Не удалось определить город. Попробуй еще раз.'
        bot.send_message(message.chat.id, text)
        return

    corrected_city = match.title()
    if corrected_city != place.title():
        bot.send_message(message.chat.id, f'Похоже, ты имел в виду "{corrected_city}".')

    if corrected_city in cache and (time.time() - cache[corrected_city]['time'] < 600):
        w = cache[corrected_city]['weather']
    else:
        try:
            observation = mgr.weather_at_place(corrected_city)
        except:
            try:
                observation = mgr.weather_at_place(f"{corrected_city},RU")
            except Exception:
                bot.send_message(message.chat.id, 'Ошибка при получении данных о погоде.')
                return
        w = observation.weather
        cache[corrected_city] = {'weather': w, 'time': time.time()}

    temp = w.temperature('celsius')['temp']
    feels = w.temperature('celsius')['feels_like']
    status = w.detailed_status
    wind = w.wind()['speed']
    humidity = w.humidity

    answer = (
        f'В городе {corrected_city} сейчас {status}.\n'
        f'Температура: {round(temp)}°C (ощущается как {round(feels)}°C).\n'
        f'Ветер: {wind} м/с, Влажность: {humidity}%.\n'
    )

    if temp < 10:
        answer += 'Сейчас ппц как холодно, одевайся тепло.'
    elif temp < 20:
        answer += 'Сейчас прохладно, оденься теплее.'
    else:
        answer += 'Жарко, можно в футболке.'

    bot.send_message(message.chat.id, answer)


# --- Запуск ---
if __name__ == '__main__':
    Thread(target=run_flask).start()
    bot.infinity_polling()
