"""
Модуль для парсинга JSON файлов, содержащих данные о проекте и telegram_id
"""
import json
from typing import Dict, List, Any, Union


def parse_json_request(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Парсит JSON запрос и извлекает telegram_id и файлы проекта.
    
    Args:
        json_data: Словарь с данными из JSON файла
        
    Returns:
        Словарь с ключами:
        - telegram_id: ID телеграм пользователя
        - files: Список файлов проекта
    """
    if "files" not in json_data:
        raise ValueError("Missing 'files' field in JSON")
    
    files_list = json_data["files"]
    
    if not isinstance(files_list, list) or len(files_list) == 0:
        raise ValueError("'files' must be a non-empty list")
    
    # Первый элемент должен содержать telegram_id
    first_item = files_list[0]
    
    if "telegram id" not in first_item and "telegram_id" not in first_item:
        raise ValueError("First item in 'files' must contain 'telegram id' or 'telegram_id'")
    
    # Извлекаем telegram_id (поддерживаем оба варианта написания)
    telegram_id = first_item.get("telegram id") or first_item.get("telegram_id")
    
    if not telegram_id:
        raise ValueError("telegram_id not found in first file item")
    
    # Остальные элементы - это файлы проекта
    project_files = files_list[1:]
    
    # Валидация файлов
    validated_files = []
    for file_item in project_files:
        if "name" not in file_item:
            raise ValueError("Each file must have 'name' field")
        
        if "content" not in file_item:
            raise ValueError(f"File '{file_item['name']}' must have 'content' field")
        
        validated_files.append({
            "name": file_item["name"],
            "content": file_item["content"]
        })
    
    return {
        "telegram_id": str(telegram_id),
        "files": validated_files
    }


def validate_file_content(file_name: str, content: Union[str, Dict]) -> bool:
    """
    Проверяет валидность содержимого файла.
    
    Args:
        file_name: Имя файла
        content: Содержимое файла (строка или словарь)
        
    Returns:
        True если файл валидный
    """
    # Базовые проверки
    if isinstance(content, dict):
        # Для JSON файлов можно добавить дополнительную валидацию
        return True
    elif isinstance(content, str):
        return True
    else:
        return False

