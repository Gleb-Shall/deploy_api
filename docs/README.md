# Материалы для презентации

Этот каталог содержит все материалы для презентации проекта деплоя.

## Структура

1. **1_deployment_pipeline.puml** — Deployment Pipeline Diagram (PlantUML activity)
2. **2_component_diagram.puml** — Component Diagram (PlantUML component)
3. **3_vcs_sequence.puml** — VCS Sequence Diagram (PlantUML sequence)
4. **4_versioning_model.md** — Модель версионирования (Git-based)
5. **5_git_integration.md** — Git Integration (описание)
6. **6_infrastructure.md** — Инфраструктурная схема (описание)
   - **6_infrastructure.puml** — Системные скрипты и их взаимодействие

## Как использовать

### Просмотр PlantUML диаграмм

**⭐ Рекомендуется: Онлайн редактор (без установки Java)**
1. Откройте http://www.plantuml.com/plantuml/uml/
2. Скопируйте содержимое `.puml` файла
3. Вставьте в редактор — диаграмма отобразится автоматически
4. Экспортируйте в PNG/SVG через кнопку "Export"

**VS Code (требует Java):**
- ⚠️ Расширение "PlantUML" требует установленный Java Runtime
- Если Java не установлен, используйте онлайн редактор выше
- Если Java установлен: откройте `.puml` файл → `Alt+D` для предпросмотра

**Альтернатива: VS Code расширение без Java:**
- Установите расширение **"Markdown Preview Mermaid Support"** или **"Mermaid Preview"**
- Но это для Mermaid, не PlantUML (нужно будет переписать диаграммы)

**Локально (если установлен Java):**
```bash
# Установка PlantUML (требует Java)
npm install -g node-plantuml

# Генерация PNG
plantuml 1_deployment_pipeline.puml
plantuml 2_component_diagram.puml
plantuml 3_vcs_sequence.puml
```

**Через Docker (если Docker запущен):**
```bash
docker run --rm -v "$(pwd):/work" plantuml/plantuml -tpng *.puml
```

### Просмотр Markdown

Просто откройте `.md` файлы в любом Markdown-редакторе или на GitHub.

## Краткое описание

### 1. Deployment Pipeline
Диаграмма потока деплоя от `git push` до доступности сайта. Показывает все этапы: SSH, git_wrap, post-receive, Redis очередь, Docker build, контейнер, Nginx.

### 2. Component Diagram
Архитектурная диаграмма компонентов системы: Git, Redis, Docker, Nginx, Storage. Показывает связи между компонентами.

### 3. VCS Sequence Diagram
Диаграмма последовательности работы с версиями: пользователь делает правки → git push → деплой → preview. Показывает взаимодействие всех участников.

### 4. Versioning Model
Описание модели версионирования: Git-based подход, как хранятся версии, как делать откат, как хранить варианты.

### 5. Git Integration
Детальное описание интеграции с Git: SSH forced command, git_wrap.sh, post-receive hook, безопасность, отладка.

### 6. Infrastructure
Инфраструктурная схема: системные скрипты и их взаимодействие. Показывает:
- Системные скрипты (git_wrap, post-receive, deploy_worker, deploy_single, docker_pull_images)
- Поток данных между скриптами
- Взаимодействие с компонентами (Redis, Docker, Nginx, файловая система)

## Для презентации

Рекомендуемый порядок:

1. **Infrastructure** (6) — общая архитектура
2. **Component Diagram** (2) — компоненты системы
3. **Deployment Pipeline** (1) — как работает деплой
4. **VCS Sequence** (3) — workflow пользователя
5. **Git Integration** (5) — технические детали Git
6. **Versioning Model** (4) — как хранятся версии

## Экспорт для презентации

### PNG изображения (PlantUML)
```bash
plantuml -tpng *.puml
# Или конкретные файлы:
plantuml -tpng 1_deployment_pipeline.puml
plantuml -tpng 2_component_diagram.puml
plantuml -tpng 3_vcs_sequence.puml
plantuml -tpng 6_infrastructure.puml
```

### PDF (через Markdown)
```bash
# Используя pandoc
pandoc 4_versioning_model.md -o 4_versioning_model.pdf
pandoc 5_git_integration.md -o 5_git_integration.pdf
pandoc 6_infrastructure.md -o 6_infrastructure.pdf
```

### Единый PDF
```bash
# Объединить все Markdown
cat 4_versioning_model.md 5_git_integration.md 6_infrastructure.md > all_docs.md
pandoc all_docs.md -o presentation_docs.pdf
```

## Примечания

- Все диаграммы используют тему `plain` для читаемости
- Цвета: синий (#2E86AB) для границ, светло-голубой (#E8F4F8) для фона
- Диаграммы можно редактировать под стиль презентации
