import os

def create_project_summary(root_dir, output_file):
    """
    Создает один файл, содержащий структуру проекта и содержимое всех .py файлов.

    Args:
        root_dir (str): Путь к корневой директории проекта (например, 'src').
        output_file (str): Имя файла для сохранения результата.
    """
    if not os.path.isdir(root_dir):
        print(f"Ошибка: Директория '{root_dir}' не найдена.")
        return

    with open(output_file, 'w', encoding='utf-8') as f:
        # Записываем заголовок
        f.write("# Файловая структура проекта\n\n")

        # Получаем и записываем структуру
        for dirpath, dirnames, filenames in os.walk(root_dir):
            level = dirpath.replace(root_dir, '').count(os.sep)
            indent = '    ' * level
            f.write(f'{indent}📁 {os.path.basename(dirpath)}/\n')
            subindent = '    ' * (level + 1)
            for file in filenames:
                if file.endswith('.py'):
                    f.write(f'{subindent}📄 {file}\n')

        # Записываем содержимое файлов
        f.write("\n\n---")
        f.write("\n\n# Содержимое Python-файлов\n\n")

        for dirpath, _, filenames in os.walk(root_dir):
            for file in filenames:
                if file.endswith('.py') and file != '__init__.py':
                    filepath = os.path.join(dirpath, file)
                    relative_path = os.path.relpath(filepath, root_dir)
                    f.write(f"## Файл: `{relative_path}`\n\n")
                    try:
                        with open(filepath, 'r', encoding='utf-8') as py_file:
                            content = py_file.read()
                            f.write(f"```python\n{content}\n```\n\n")
                    except Exception as e:
                        f.write(f"```\nОшибка чтения файла: {e}\n```\n\n")

    print(f"Файл '{output_file}' успешно создан.")

# --- Пример использования ---
# Укажи путь к твоей папке src
SRC_DIRECTORY = 'src'
# Укажи имя выходного файла
OUTPUT_FILE = 'project_summary.md'

create_project_summary(SRC_DIRECTORY, OUTPUT_FILE)