import os
import re
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal
import sys

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Глобальная переменная для отслеживания завершенности процесса
shutdown_flag = False

def signal_handler(sig, frame):
    global shutdown_flag
    logging.info('Получен сигнал завершения, пожалуйста, подождите...')
    shutdown_flag = True

# Назначение обработчика сигнала
signal.signal(signal.SIGINT, signal_handler)

def translate_text(text, src_lang='en', dest_lang='ru'):
    """
    Переводит текст, игнорируя части, которые не должны быть переведены (имена, архивы, ссылки и команды).
    """
    if not text:
        return text

    # Регулярные выражения для поиска имен, архивов, ссылок и команд
    patterns = [
        r'`[^`]+`',               # Команды в обратных кавычках
        r'https?://[^\s]+',       # URL-ссылки
        r'[A-Za-z0-9._-]+\.[a-z]+',  # Архивы и имена файлов
    ]

    # Найти все совпадения
    matches = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text))

    # Заменить совпадения на уникальные плейсхолдеры
    placeholders = {f"<PLACEHOLDER_{i}>": match for i, match in enumerate(matches)}
    for placeholder, match in placeholders.items():
        text = text.replace(match, placeholder)

    # Перевести оставшийся текст
    translated = GoogleTranslator(source=src_lang, target=dest_lang).translate(text)

    # Вернуть совпадения на их место
    for placeholder, match in placeholders.items():
        translated = translated.replace(placeholder, match)

    return translated

def translate_html(input_file, output_file, src_lang='en', dest_lang='ru'):
    """
    Переводит HTML-файл, сохраняя теги и атрибуты, а также игнорируя ссылки, команды и имена файлов.
    """
    if shutdown_flag:
        return

    try:
        # Чтение исходного HTML-файла
        with open(input_file, 'r', encoding='utf-8') as infile:
            soup = BeautifulSoup(infile, 'html.parser')

        # Перевод всех текстовых элементов в HTML
        for element in soup.find_all(text=True):
            if shutdown_flag:
                return
            if element.parent.name not in ['script', 'style', 'code', 'pre']:  # Исключаем теги скриптов и стилей
                translated_text = translate_text(element.string, src_lang, dest_lang)
                if translated_text:
                    element.string.replace_with(translated_text)

        # Запись переведённого HTML в новый файл
        with open(output_file, 'w', encoding='utf-8') as outfile:
            outfile.write(str(soup))

        logging.info(f"Перевод завершен для: {input_file}, результат сохранен в {output_file}")
    except Exception as e:
        logging.error(f"Ошибка при переводе файла {input_file}: {e}")

def copy_file(input_file, output_file):
    """
    Копирует файл и выводит сообщение в лог.
    """
    if shutdown_flag:
        return

    try:
        shutil.copy2(input_file, output_file)
        logging.info(f"Файл скопирован: {input_file} -> {output_file}")
    except Exception as e:
        logging.error(f"Ошибка при копировании файла {input_file}: {e}")

def translate_directory(src_directory, dest_directory, src_lang='en', dest_lang='ru'):
    """
    Обрабатывает все файлы в указанной директории и её подпапках, сохраняя структуру.
    """
    tasks = []

    # Пройти по всем файлам в директории и подпапках
    for root, dirs, files in os.walk(src_directory):
        for file in files:
            input_file = os.path.join(root, file)

            # Создание соответствующей структуры директорий в целевой папке
            relative_path = os.path.relpath(input_file, src_directory)
            output_file = os.path.join(dest_directory, relative_path)

            # Создаём директорию, если её ещё нет
            os.makedirs(os.path.dirname(output_file), exist_ok=True)

            if file.lower().endswith(('.html', '.htm')):  # Проверяем, что файл является HTML
                # Добавляем задачу на перевод
                tasks.append((translate_html, input_file, output_file, src_lang, dest_lang))
            else:
                # Добавляем задачу на копирование
                tasks.append((copy_file, input_file, output_file))

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_task = {executor.submit(task[0], *task[1:]): task for task in tasks}

        for future in as_completed(future_to_task):
            if shutdown_flag:
                break
            task = future_to_task[future]
            try:
                future.result()
            except Exception as e:
                logging.error(f"Ошибка при выполнении задачи {task}: {e}")

# Использование
src_directory = os.path.expanduser('~/public_html/blfs-book')
dest_directory = os.path.expanduser('~/public_html/blfs-ru')

# Если целевая директория уже существует, очистим её
if os.path.exists(dest_directory):
    shutil.rmtree(dest_directory)
    logging.info(f"Директория {dest_directory} очищена")

# Переводим все файлы
translate_directory(src_directory, dest_directory)

if shutdown_flag:
    logging.info("Процесс завершен пользователем.")
else:
    logging.info("Все файлы успешно переведены и скопированы.")