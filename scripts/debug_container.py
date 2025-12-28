"""
Скрипт для отладки контейнера - показывает что внутри
"""
import subprocess
import sys

def check_container(container_name="deploy-1d2637e8889b"):
    """Проверяет содержимое контейнера"""
    print("=" * 60)
    print(f"ОТЛАДКА КОНТЕЙНЕРА: {container_name}")
    print("=" * 60)
    
    # Проверяем статус
    print("\n📦 Статус контейнера:")
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
        capture_output=True,
        text=True
    )
    print(result.stdout if result.returncode == 0 else "Контейнер не найден")
    
    # Проверяем логи
    print("\n📋 Последние логи (30 строк):")
    result = subprocess.run(
        ["docker", "logs", container_name, "--tail", "30"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print("Не удалось получить логи")
    
    # Проверяем содержимое dist
    print("\n📁 Содержимое /usr/share/nginx/html:")
    result = subprocess.run(
        ["docker", "exec", container_name, "ls", "-la", "/usr/share/nginx/html/"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(result.stdout)
    else:
        print("Не удалось получить список файлов")
    
    # Ищем HTML файлы
    print("\n📄 HTML файлы:")
    result = subprocess.run(
        ["docker", "exec", container_name, "find", "/usr/share/nginx/html", "-name", "*.html"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(result.stdout)
    
    # Ищем CSS файлы
    print("\n🎨 CSS файлы:")
    result = subprocess.run(
        ["docker", "exec", container_name, "find", "/usr/share/nginx/html", "-name", "*.css"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print(result.stdout if result.stdout.strip() else "CSS файлы не найдены (возможно инлайнятся в HTML)")
    
    # Проверяем index.html на наличие стилей
    print("\n🔍 Проверка index.html (первые 100 строк):")
    result = subprocess.run(
        ["docker", "exec", container_name, "head", "-100", "/usr/share/nginx/html/index.html"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        html = result.stdout
        print(html[:2000])  # Первые 2000 символов
        
        # Ищем стили
        if '<style' in html:
            print("\n✅ Найдены <style> теги в HTML")
        if 'style=' in html:
            print("✅ Найдены inline стили")
        if '.css' in html or 'stylesheet' in html:
            print("✅ Найдены ссылки на CSS файлы")
        if not ('<style' in html or 'style=' in html or '.css' in html):
            print("⚠️  Стили не найдены в HTML!")
    else:
        print("Не удалось прочитать index.html")
    
    # Проверяем структуру dist
    print("\n📂 Структура dist:")
    result = subprocess.run(
        ["docker", "exec", container_name, "find", "/usr/share/nginx/html", "-type", "f", "-name", "*"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        files = result.stdout.strip().split('\n')
        print(f"Всего файлов: {len(files)}")
        for f in files[:20]:  # Первые 20 файлов
            print(f"  {f}")

if __name__ == "__main__":
    container_name = sys.argv[1] if len(sys.argv) > 1 else "deploy-1d2637e8889b"
    check_container(container_name)

