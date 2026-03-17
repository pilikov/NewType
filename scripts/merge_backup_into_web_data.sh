#!/bin/bash
# Merge бэкапа в web/data: копируем только отсутствующие папки, не перезаписываем.
# Использование: ./scripts/merge_backup_into_web_data.sh [путь_к_бэкапу]

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP="${1:-$ROOT/backups/backup_data_20260310_190916}"
TARGET="$ROOT/web/data"

if [ ! -d "$BACKUP" ]; then
  echo "Бэкап не найден: $BACKUP"
  exit 1
fi

echo "Merge из $BACKUP в $TARGET (только отсутствующие)"
for src_dir in "$BACKUP"/*/; do
  [ -d "$src_dir" ] || continue
  src=$(basename "$src_dir")
  if [ "$src" = "_meta" ]; then
    continue
  fi
  tgt="$TARGET/$src"
  mkdir -p "$tgt"
  for item in "$src_dir"/*; do
    [ -e "$item" ] || continue
    name=$(basename "$item")
    if [ -d "$item" ]; then
      if [ ! -d "$tgt/$name" ]; then
        cp -r "$item" "$tgt/"
        echo "  + $src/$name"
      fi
    else
      if [ ! -f "$tgt/$name" ]; then
        cp "$item" "$tgt/"
        echo "  + $src/$name"
      fi
    fi
  done
done
echo "Готово."
