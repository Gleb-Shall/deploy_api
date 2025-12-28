"""
Вспомогательные утилиты
"""
import hashlib
import json
from typing import List, Dict, Any


def generate_hash(telegram_id: str, files: List[Dict[str, Any]]) -> str:
    """
    Генерирует уникальный хэш на основе telegram_id и содержимого файлов.
    
    Args:
        telegram_id: ID телеграм пользователя
        files: Список файлов проекта
        
    Returns:
        Уникальный хэш строки (первые 12 символов SHA256)
    """
    # Создаем строку для хэширования
    data_string = f"{telegram_id}"
    
    # Добавляем информацию о файлах (имена и содержимое)
    for file_data in sorted(files, key=lambda x: x["name"]):
        data_string += f"{file_data['name']}"
        if isinstance(file_data["content"], dict):
            data_string += json.dumps(file_data["content"], sort_keys=True)
        else:
            data_string += str(file_data["content"])
    
    # Генерируем хэш
    hash_obj = hashlib.sha256(data_string.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    
    # Возвращаем первые 12 символов для читаемости
    return hash_hex[:12]


def prepare_file_content(content: Any) -> str:
    """
    Преобразует содержимое файла в строку для записи.
    
    Args:
        content: Содержимое файла (строка или словарь)
        
    Returns:
        Строковое представление содержимого
    """
    if isinstance(content, dict):
        return json.dumps(content, indent=2, ensure_ascii=False)
    return str(content)

