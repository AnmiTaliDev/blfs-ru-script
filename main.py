import os
import re
from translate import Translator
from bs4 import BeautifulSoup
import shutil
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal

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

    translator = Translator(from_lang=src_lang, to_lang=dest_lang)
    
    # Регулярные выражения для поиска имен, архивов, ссылок и команд
    patterns = [
        r'`[^`]+`',                # Команды в обратных кавычках
        r'https?://[^\s]+',        # URL-ссылки
        r'[A-Za-z0-9._-]+\.[a-z]+', # Архивы и имена файлов
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
    translated = translator.translate(text)

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
        for element in soup.find_all(string=True):
            if shutdown_flag:
                return
            if element.parent.name not in ['script', 'style', 'code', 'pre']:  # Исключаем теги скриптов и стилей
                translated_text = translate_text(element.string, src_lang, dest_lang)
                if translated_text:
                    element.string.replace_with(translated_text)

        # Удаление строки <?xml version="1.0" encoding="utf-8" standalone="no"?>
        if soup.contents and str(soup.contents[0]).startswith('<?xml'):
            soup.contents[0].extract()

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

def copy_directory_structure(src_directory, dest_directory):
    """
    Копирует структуру директорий из исходной директории в целевую.
    """
    for root, dirs, files in os.walk(src_directory):
        for dir in dirs:
            src_dir = os.path.join(root, dir)
            relative_path = os.path.relpath(src_dir, src_directory)
            dest_dir = os.path.join(dest_directory, relative_path)
            os.makedirs(dest_dir, exist_ok=True)
            logging.info(f"Директория создана: {src_dir} -> {dest_dir}")

def translate_directory(src_directory, dest_directory, src_lang='en', dest_lang='ru'):
    """
    Обрабатывает все файлы в указанной директории и её подпапках, сохраняя структуру.
    """
    # Сначала копируем структуру директорий
    copy_directory_structure(src_directory, dest_directory)

    copy_tasks = []
    translate_tasks = []

    # Пройти по всем файлам в директории и подпапках
    for root, dirs, files in os.walk(src_directory):
        for file in files:
            input_file = os.path.join(root, file)

            # Создание соответствующей структуры директорий в целевой папке
            relative_path = os.path.relpath(input_file, src_directory)
            output_file = os.path.join(dest_directory, relative_path)

            if file.lower().endswith(('.html', '.htm')):  # Проверяем, что файл является HTML
                # Добавляем задачу на перевод
                translate_tasks.append((translate_html, input_file, output_file, src_lang, dest_lang))
            else:
                # Добавляем задачу на копирование
                copy_tasks.append((copy_file, input_file, output_file))

    # Сначала выполняем задачи копирования
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_task = {executor.submit(task[0], *task[1:]): task for task in copy_tasks}

        for future in as_completed(future_to_task):
            if shutdown_flag:
                break
            task = future_to_task[future]
            try:
                future.result()
            except Exception as e:
                logging.error(f"Ошибка при выполнении задачи {task}: {e}")

    # Затем выполняем задачи перевода
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_task = {executor.submit(task[0], *task[1:]): task for task in translate_tasks}

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