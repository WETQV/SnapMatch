# Пример MCP-сервера

`simple_snapmatch_mcp.py` - минимальный MCP-сервер для проверки интеграции SnapMatch.

## Запуск отдельно

```sh
python examples/mcp/simple_snapmatch_mcp.py
```

Сервер рассчитан на запуск через `stdio`, поэтому при обычном запуске он может ждать запросы от MCP-клиента.

## Добавление в SnapMatch

В GUI откройте вкладку MCP и добавьте сервер:

```txt
name: simple_snapmatch_mcp
transport: stdio
command: python
args: examples/mcp/simple_snapmatch_mcp.py
enabled: true
```

После сохранения перезапустите бота или MCP-runtime. Если сервер появился в списке и tools доступны, интеграция работает.

## Диагностика

- Проверьте, что путь к файлу указан относительно корня проекта.
- Если используется virtualenv, укажите полный путь к `python.exe`.
- Если tool не появляется, посмотрите stderr процесса и журнал приложения.
- Не подключайте MCP-серверы, которым не доверяете.
