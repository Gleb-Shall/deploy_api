# Screenshot API — скриншоты Playwright (модуль генерации)

Отдельный порт от domain_api. Принимает скриншоты от Playwright и сохраняет на диск.

- **Порт:** 5051 (по умолчанию)
- **Загрузка:** `POST http://127.0.0.1:5051/api/screenshots` — multipart поле `file` или raw body (изображение)
- **Просмотр:** `GET http://127.0.0.1:5051/screenshot/<id>`

Опционально: в `.env` задать `SCREENSHOT_API_KEY` — тогда загрузка только с заголовком `X-API-Key`.  
Хранение: `SCREENSHOT_STORAGE_DIR` (по умолчанию `/opt/deploy/screenshots`), подпапки `pictures/` и `meta/`.

### Запуск вручную

```bash
pip install -r requirements.txt && python api.py
```

### Автозапуск (systemd)

На сервере после деплоя проекта в `/opt/deploy_api` установи зависимости (из каталога `screenshot_api`: `pip install -r requirements.txt` или создай venv и в unit укажи `ExecStart=.../venv/bin/python api.py`), затем:

```bash
sudo bash scripts/server_setup/install_api_services.sh
```

Сервис `screenshot_api` будет включён и перезапускаться при перезагрузке. Логи: `journalctl -u screenshot_api -f`.
