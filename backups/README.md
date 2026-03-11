# Бэкапы данных

Бэкапы создаются вручную перед важными изменениями.

- **backup_data_YYYYMMDD_HHMMSS** — копия `web/data/`
- **backup_data_YYYYMMDD_HHMMSS_state** — копия `state/` (водяные знаки, coverage и т.д.)

Пример: `backup_data_20260310_190916` — бэкап от 10 марта 2026, 19:09.

Восстановление (если нужно):
```bash
cp -r backups/backup_data_YYYYMMDD_HHMMSS/* web/data/
cp -r backups/backup_data_YYYYMMDD_HHMMSS_state/* state/
```
