#!/bin/sh
# Находит рабочий Python 3.9+ и запускает им скрипт из tools/.
# На Windows команда python3 часто оказывается заглушкой магазина приложений: её пропускаем.
dir="$(cd "$(dirname "$0")" && pwd)"
script="$1"; shift
for py in python3 python py; do
  if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    PYTHONUTF8=1 exec "$py" "$dir/$script" "$@"
  fi
done
echo "Не найден Python 3.9 или новее. Установи его с python.org и повтори." >&2
exit 127
