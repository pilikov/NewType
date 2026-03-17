#!/bin/bash
# Восстановить web/data из бэкапа (после потери из-за Mirror rm -rf).
# Использование: ./scripts/restore_web_data_from_backup.sh [путь_к_бэкапу]
#
# Бэкап от 10 марта: backups/backup_data_20260310_190916/

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP="${1:-$ROOT/backups/backup_data_20260310_190916}"
TARGET="$ROOT/web/data"

if [ ! -d "$BACKUP" ]; then
  echo "Бэкап не найден: $BACKUP"
  exit 1
fi

echo "Восстановление из $BACKUP в $TARGET"
for dir in "$BACKUP"/*/; do
  [ -d "$dir" ] || continue
  src=$(basename "$dir")
  if [ "$src" = "_meta" ] && [ -d "$TARGET/_meta" ]; then
    echo "  Пропуск _meta (сохраняем текущие favicons)"
    continue
  fi
  mkdir -p "$TARGET/$src"
  cp -r "$dir"/* "$TARGET/$src/" 2>/dev/null || true
  echo "  Восстановлено: $src"
done
echo "Готово. Проверьте web/data и закоммитьте при необходимости."
