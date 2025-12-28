"""
Менеджер для генерации конфигураций nginx
"""
from typing import Optional


class NginxManager:
    """Управление конфигурациями nginx"""
    
    def __init__(self, domain: str = "your-domain.com"):
        self.domain = domain
    
    def generate_nginx_location(
        self,
        page_hash: str,
        container_port: int = 8000,
        upstream_name: Optional[str] = None
    ) -> str:
        """
        Генерирует location блок nginx для проксирования к контейнеру по пути /{hash}.
        
        Args:
            page_hash: Уникальный хэш страницы
            container_port: Порт контейнера
            upstream_name: Имя upstream блока (по умолчанию использует page_hash)
            
        Returns:
            Строка с location блоком nginx
        """
        if upstream_name is None:
            upstream_name = f"deploy_{page_hash}"
        
        location_config = f"""# Location для /{page_hash}
location /{page_hash}/ {{
    proxy_pass http://127.0.0.1:{container_port}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_cache_bypass $http_upgrade;
    
    # Таймауты
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    
    # Убираем /{page_hash} из пути при проксировании к контейнеру
    rewrite ^/{page_hash}(/.*)$ $1 break;
}}

# Location для статических файлов Astro (/_astro/, /assets/ и т.д.)
# Эти файлы запрашиваются без префикса /{page_hash}, поэтому проксируем напрямую
location ~ ^/(_astro|assets|node_modules|public)/ {{
    proxy_pass http://127.0.0.1:{container_port}$request_uri;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # Кеширование статических файлов
    expires 1y;
    add_header Cache-Control "public, immutable";
}}

# Редирект с /{page_hash} на /{page_hash}/
location = /{page_hash} {{
    return 301 /{page_hash}/;
}}
"""
        return location_config
    
    def get_config_path(self, page_hash: str) -> str:
        """Возвращает путь где должна быть сохранена конфигурация location блока"""
        return f"/etc/nginx/sites-available/deploy/{page_hash}.conf"

