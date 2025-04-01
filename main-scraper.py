# Запускати це працююче.py
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By  # Додано імпорт By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from scraper import parse_schedule_html_to_json

# --- Налаштування ---
URL = "https://asu-srv.pnu.edu.ua/cgi-bin/timetable.cgi"
GROUPS = [
    "КН-11", "КН-12", "КН-13", "КН-21", "КН-22", "КН-23", "КН-31", "КН-32", "КН-41",
    "ІПЗ-11", "ІПЗ-12", "ІПЗ-21", "ІПЗ-22",
    "ІСТ-11", "ІСТ-12", "ІСТ-21",
    "ПР-31", "ПР-32", "ПР-33", "ПР-34", "ПР-35"
]
START_DATE = "10.02.2025"
END_DATE = "31.06.2025"
OUTPUT_JS_FILE = "schedule_data.js"
WAIT_TIMEOUT = 15
SLEEP_BETWEEN_REQUESTS = 1


def load_existing_data(filename):
    """Завантажує існуючі дані з файлу, якщо він існує"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
            json_str = content.replace('const schedulesData =', '').replace(';\n', '').strip()
            return json.loads(json_str)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        print(f"Помилка при завантаженні існуючих даних: {e}")
        return {}


def compare_schedules(old_data, new_data):
    """Порівнює старі та нові дані та повертає список змін"""
    changes = []

    for group_name, new_group_data in new_data.items():
        if group_name not in old_data:
            changes.append(f"{group_name}: додано нову групу")
            continue

        old_group_data = old_data[group_name]

        if old_group_data.get('date_range') != new_group_data.get('date_range'):
            changes.append(
                f"{group_name}: змінився діапазон дат з {old_group_data.get('date_range')} на {new_group_data.get('date_range')}")

        old_days = {day['date']: day for day in old_group_data.get('schedule', [])}
        new_days = {day['date']: day for day in new_group_data.get('schedule', [])}

        all_dates = set(old_days.keys()).union(set(new_days.keys()))

        for date in all_dates:
            if date not in old_days:
                changes.append(f"{group_name}: додано новий день {date} ({new_days[date]['day']})")
                continue
            if date not in new_days:
                changes.append(f"{group_name}: видалено день {date} ({old_days[date]['day']})")
                continue

            old_lessons = old_days[date]['lessons']
            new_lessons = new_days[date]['lessons']

            if len(old_lessons) != len(new_lessons):
                changes.append(
                    f"{group_name}: змінилася кількість занять {date} (було {len(old_lessons)}, стало {len(new_lessons)})")
            else:
                for i, (old_lesson, new_lesson) in enumerate(zip(old_lessons, new_lessons)):
                    if old_lesson != new_lesson:
                        changes.append(f"{group_name}: змінилося заняття {date} пара {i + 1} ({old_lesson['time']})")
                        for key in ['subject', 'teacher', 'group', 'details']:
                            if old_lesson.get(key) != new_lesson.get(key):
                                changes.append(
                                    f"  - {key}: було '{old_lesson.get(key)}', стало '{new_lesson.get(key)}'")

    return changes


# Завантажуємо існуючі дані
existing_data = load_existing_data(OUTPUT_JS_FILE)
print(f"Завантажено існуючі дані для {len(existing_data)} груп")

# --- Ініціалізація WebDriver ---
service = ChromeService(ChromeDriverManager().install())
options = webdriver.ChromeOptions()
options.add_argument("--headless")
driver = webdriver.Chrome(service=service, options=options)

print(f"WebDriver запущено. Починаємо збір даних для {len(GROUPS)} груп...")

all_groups_data = {}

# --- Основний цикл по групам ---
for group in GROUPS:
    print(f"\nОбробка групи: {group}")
    try:
        driver.get(URL)

        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        group_input = wait.until(EC.presence_of_element_located((By.ID, "group")))
        sdate_input = wait.until(EC.presence_of_element_located((By.ID, "sdate")))
        edate_input = wait.until(EC.presence_of_element_located((By.ID, "edate")))
        submit_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(text(), 'Показати розклад')]")))

        group_input.clear()
        group_input.send_keys(group)
        sdate_input.clear()
        sdate_input.send_keys(START_DATE)
        edate_input.clear()
        edate_input.send_keys(END_DATE)
        time.sleep(0.5)
        submit_button.click()

        results_container_locator = (
        By.XPATH, f"//div[@class='container'][.//h4[contains(., 'Розклад групи {group}')]]")
        results_container = wait.until(EC.presence_of_element_located(results_container_locator))
        container_html = results_container.get_attribute('outerHTML')

        parsed_data, parsed_group_name = parse_schedule_html_to_json(container_html)

        if parsed_group_name != "Невідома група" and parsed_group_name in parsed_data:
            all_groups_data.update(parsed_data)
            print(f"  Дані для групи {parsed_group_name} успішно додано.")
        else:
            print(f"  ПОМИЛКА: Не вдалося коректно розпарсити дані або назву для групи {group}.")

    except TimeoutException:
        print(f"  ПОМИЛКА: Не вдалося знайти розклад для групи '{group}' за {WAIT_TIMEOUT} секунд.")
    except Exception as e:
        print(f"  ПОМИЛКА: Неочікувана помилка при обробці групи '{group}': {e}")
    finally:
        time.sleep(SLEEP_BETWEEN_REQUESTS)

# --- Завершення роботи ---
driver.quit()
print("\nWebDriver закрито.")

if all_groups_data:
    changes = compare_schedules(existing_data, all_groups_data)

    if changes:
        print("\nЗнайдено зміни в розкладах:")
        for change in changes:
            print(f" - {change}")
    else:
        print("\nЗмін в розкладах не виявлено.")

    js_output_string = f"const schedulesData = {json.dumps(all_groups_data, indent=4, ensure_ascii=False)};\n\n"

    try:
        with open(OUTPUT_JS_FILE, 'w', encoding='utf-8') as f:
            f.write(js_output_string)
        print(f"\nУспішно збережено дані в файл: {OUTPUT_JS_FILE}")
    except Exception as e:
        print(f"\nПОМИЛКА: Не вдалося зберегти дані у файл {OUTPUT_JS_FILE}: {e}")
else:
    print("\nНе вдалося зібрати дані для жодної групи.")

print("\nРоботу завершено.")
