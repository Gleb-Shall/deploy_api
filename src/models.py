from pydantic import BaseModel
from typing import List, Dict, Any, Union


class DeployRequest(BaseModel):
    """Модель запроса на деплой"""
    telegram_id: str
    files: List[Dict[str, Union[str, Dict[str, Any]]]]


class DeployResponse(BaseModel):
    """Модель ответа после деплоя"""
    telegram_id: str
    url: str


class FileData(BaseModel):
    """Модель файла проекта"""
    name: str
    content: Union[str, Dict[str, Any]]

