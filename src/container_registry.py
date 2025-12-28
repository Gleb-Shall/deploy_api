"""
Реестр контейнеров для отслеживания соответствия хэш -> контейнер -> порт
"""
import json
import os
from typing import Dict, Optional


class ContainerRegistry:
    """Реестр для управления контейнерами и их соответствием хэшам"""
    
    def __init__(self, registry_file: str = "/opt/deploy/registry.json"):
        self.registry_file = registry_file
        self.registry: Dict[str, Dict] = {}
        self._load_registry()
    
    def _load_registry(self):
        """Загружает реестр из файла"""
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, 'r', encoding='utf-8') as f:
                    self.registry = json.load(f)
            except Exception:
                self.registry = {}
        else:
            self.registry = {}
    
    def _save_registry(self):
        """Сохраняет реестр в файл"""
        os.makedirs(os.path.dirname(self.registry_file), exist_ok=True)
        with open(self.registry_file, 'w', encoding='utf-8') as f:
            json.dump(self.registry, f, indent=2, ensure_ascii=False)
    
    def get_container_info(self, page_hash: str) -> Optional[Dict]:
        """
        Получает информацию о контейнере по хэшу.
        
        Returns:
            Словарь с информацией о контейнере или None
        """
        return self.registry.get(page_hash)
    
    def register_container(
        self,
        page_hash: str,
        container_name: str,
        container_port: int,
        image_name: str
    ):
        """
        Регистрирует контейнер в реестре.
        
        Args:
            page_hash: Уникальный хэш страницы
            container_name: Имя контейнера
            container_port: Порт контейнера на хосте
            image_name: Имя Docker образа
        """
        self.registry[page_hash] = {
            "container_name": container_name,
            "container_port": container_port,
            "image_name": image_name,
            "page_hash": page_hash
        }
        self._save_registry()
    
    def container_exists(self, page_hash: str) -> bool:
        """Проверяет, существует ли контейнер для данного хэша"""
        return page_hash in self.registry
    
    def get_all_containers(self) -> Dict[str, Dict]:
        """Возвращает все зарегистрированные контейнеры"""
        return self.registry.copy()

