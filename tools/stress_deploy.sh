#!/bin/bash
#
# Параллельный push нескольких сайтов на сервер (стресс-тест)
# Использование: ./stress_deploy.sh SITES_DIR [SERVER] [--monitor]
#
# SITES_DIR   — папка с подпапками, каждая подпапка = готовый сайт (Astro и т.п.)
# SERVER      — git@host или host (по умолчанию git@45.90.35.151)
# --monitor   — собирать load/CPU/disk на сервере во время деплоя (требует root@host)
#
# Скрипт копирует каждый сайт, инициализирует git при необходимости, задаёт remote и пушит все одновременно.
#

set -e

SITES_DIR="${1:?Укажи папку с сайтами: ./stress_deploy.sh /path/to/sites}"
SERVER="git@45.90.35.151"
MONITOR=false
for arg in "$2" "$3"; do
  [[ "$arg" == "--monitor" ]] && MONITOR=true
  if [[ "$arg" == git@* ]]; then
    SERVER="$arg"
  elif [[ "$arg" == git:* ]]; then
    SERVER="git@${arg#git:}"
  elif [[ -n "$arg" && "$arg" != -* ]]; then
    SERVER="git@${arg}"
  fi
done
REMOTE_PREFIX="${SERVER}:sites/"
MONITOR_HOST="${SERVER#*@}"
TMP_BASE="/tmp/stress-deploy-$$"

if [[ ! -d "$SITES_DIR" ]]; then
  echo "Ошибка: $SITES_DIR не существует"
  exit 1
fi

# Собираем подпапки (первые 6 или все)
SHARDS=()
for d in "$SITES_DIR"/*/; do
  [[ -d "$d" ]] || continue
  SHARDS+=("$d")
done

if [[ ${#SHARDS[@]} -eq 0 ]]; then
  echo "Ошибка: в $SITES_DIR нет подпапок с сайтами"
  exit 1
fi

mkdir -p "$TMP_BASE"

MONITOR_LOG="$TMP_BASE/monitor.log"
MONITOR_PID=""
if $MONITOR; then
  echo "Мониторинг сервера root@$MONITOR_HOST (load/CPU/mem) — 2 мин..."
  ssh -o ConnectTimeout=5 -o BatchMode=yes "root@$MONITOR_HOST" \
    'cpus=$(nproc 2>/dev/null || echo 1)
     for i in $(seq 1 120); do
       load=$(cat /proc/loadavg 2>/dev/null)
       load1=$(echo "$load" | cut -d" " -f1)
       load_pct=$(awk "BEGIN {printf \"%.0f\", ($load1/$cpus)*100}" 2>/dev/null || echo "?")
       mem=$(awk "/MemAvailable/ {av=\$2} /MemTotal/ {tot=\$2} END {printf \"%d/%dMB\", av/1024, tot/1024}" /proc/meminfo 2>/dev/null)
       disk=$(awk "\$3==\"sda\" || \$3==\"vda\" {print \$4}" /proc/diskstats 2>/dev/null | head -1 || echo "-")
       echo "$(date -Iseconds) load=$load load_pct=${load_pct}% mem=$mem disk_reads=$disk"
       sleep 1
     done' > "$MONITOR_LOG" 2>/dev/null &
  MONITOR_PID=$!
  sleep 2
fi

START_TIME=$(date +%s)
echo "Подготовка ${#SHARDS[@]} сайтов..."
i=0
for SITE_SRC in "${SHARDS[@]}"; do
  NAME=$(basename "$SITE_SRC")
  HASH=$(openssl rand -hex 6)
  TMP="$TMP_BASE/$HASH"
  cp -r "$SITE_SRC" "$TMP"
  (
    cd "$TMP"
    if [[ ! -d .git ]]; then
      git init
      git add .
      git commit -m "deploy" || true
    fi
    git remote remove origin 2>/dev/null || true
    git remote add origin "$REMOTE_PREFIX${HASH}.git"
    # Переключаем на main/master если есть
    git branch -M main 2>/dev/null || git branch -M master 2>/dev/null || true
    echo "$NAME → $HASH ready"
  )
  i=$((i + 1))
done

PREP_END=$(date +%s)
PREP_DUR=$((PREP_END - START_TIME))
echo ""
echo "Параллельный push ${#SHARDS[@]} сайтов..."
PUSH_START=$(date +%s)
SUCCESS_COUNT=0
for d in "$TMP_BASE"/*/; do
  H=$(basename "$d")
  (cd "$d" && OUT=$(git push -u origin main 2>&1); R=$?; echo "$OUT" | sed "s/^/[$H] /" | tee "$TMP_BASE/$H.log"; 
   # Проверяем фактический результат деплоя, а не только код возврата git push
   if [[ $R -eq 0 ]] && grep -q "Деплой завершён успешно\|DEPLOY_URL:" "$TMP_BASE/$H.log" 2>/dev/null; then
     echo "1" > "$TMP_BASE/$H.ok"
   else
     echo "0" > "$TMP_BASE/$H.ok"
   fi) &
done
wait
for f in "$TMP_BASE"/*.ok; do
  [[ -f "$f" ]] && [[ "$(cat "$f" 2>/dev/null)" == "1" ]] && SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
done
PUSH_END=$(date +%s)
PUSH_DUR=$((PUSH_END - PUSH_START))
TOTAL_DUR=$((PUSH_END - START_TIME))

echo ""
echo "Очистка..."
if [[ -n "$MONITOR_PID" ]] && kill -0 "$MONITOR_PID" 2>/dev/null; then
  kill "$MONITOR_PID" 2>/dev/null || true
  wait "$MONITOR_PID" 2>/dev/null || true
fi

# Проверяем неудачные деплои
FAILED_HASHES=()
for f in "$TMP_BASE"/*.ok; do
  [[ -f "$f" ]] || continue
  H=$(basename "$f" .ok)
  if [[ "$(cat "$f" 2>/dev/null)" != "1" ]]; then
    FAILED_HASHES+=("$H")
  fi
done

echo ""
echo "——— Статистика ———"
echo "Подготовка:    ${PREP_DUR} сек"
echo "Push (паралл): ${PUSH_DUR} сек"
echo "Всего:         ${TOTAL_DUR} сек"
echo "Успешно:       ${SUCCESS_COUNT}/${#SHARDS[@]}"
if [[ ${#FAILED_HASHES[@]} -gt 0 ]]; then
  echo "Неудачно:      ${#FAILED_HASHES[@]}"
  echo "Провалившиеся деплои:"
  for H in "${FAILED_HASHES[@]}"; do
    echo "  - $H"
    if [[ -f "$TMP_BASE/$H.log" ]]; then
      echo "    Логи:"
      grep -E "(Ошибка|Error|failed|FAILED)" "$TMP_BASE/$H.log" 2>/dev/null | head -3 | sed "s/^/      /" || echo "      (нет ошибок в логах)"
    fi
  done
fi

if $MONITOR && [[ -f "$MONITOR_LOG" ]]; then
  echo ""
  echo "——— Нагрузка сервера ———"
  # Парсим load1 и load_pct, считаем min/max/avg, рисуем sparkline
  awk '
    /load=/ {
      sub(/.*load=/, ""); load1=$1+0
      sub(/.*load_pct=/, ""); sub(/%.*/, ""); pct=$1+0
      if (load1!="") { sum+=load1; n++; if (n==1||load1<min)min=load1; if (load1>max)max=load1; l[n]=load1 }
      if (pct!="") { psum+=pct; if (n==1){pmin=pmax=pct} else {if(pct<pmin)pmin=pct; if(pct>pmax)pmax=pct} }
    }
    END {
      avg=(n>0)?sum/n:0
      pavg=(n>0)?psum/n:0
      pmin=pmin+0; pmax=pmax+0
      printf "Load (1m): min=%.2f max=%.2f avg=%.2f\n", min, max, avg
      printf "Загрузка CPU: min=%d%% max=%d%% avg=%.0f%%  [%d сэмплов]\n", pmin, pmax, pavg, n
      # Sparkline (▁▂▃▄▅▆▇█)
      if (n>0 && max>0) {
        chars="▁▂▃▄▅▆▇█"
        for(i=1;i<=n;i++) {
          idx=int((l[i]/max)*7); if(idx<0)idx=0; if(idx>7)idx=7
          printf "%s", substr(chars,idx+1,1)
        }
        printf "\n"
      }
    }
  ' "$MONITOR_LOG"
  echo ""
  echo "Сырые данные:"
  cat "$MONITOR_LOG"
fi

rm -rf "$TMP_BASE"
echo "Готово."
