# Как скачать и запустить проект Samar Hub News Bot

Ниже — простой путь: скачать архив, распаковать, заполнить `.env`, запустить через Docker.

## 1) Скачать архив проекта

В этом репозитории подготовлен архив:

- `dist/Samar-Bot.zip`

Скачайте его и распакуйте.

## 2) Подготовка окружения

Нужно установить:

- Docker
- Docker Compose (обычно уже встроен как `docker compose`)

Проверка:

```bash
docker --version
docker compose version
```

## 3) Настройка `.env`

Рекомендация для первого старта в Docker:
- `TELETHON_ENABLED=0` (чтобы запустить только aiogram-часть без Telethon-логина)

В папке проекта:

```bash
cp .env.example .env
```

Откройте `.env` и заполните обязательные поля:

- `BOT_TOKEN`
- `OWNER_ID`
- `GROUP_ID`
- `NEWS_THREAD_ID`

Для Telethon без интерактива:
- включить `TELETHON_ENABLED=1`
- додати хоча б один READY акаунт через адмін-панель

## 4) Запуск

```bash
docker compose up --build -d
```

Проверить логи:

```bash
docker compose logs -f bot
```

## 5) Базовые команды в Telegram

- Пользователь: `/start`, `/news`
- Админ: `/queue`, `/mylocks`
- Owner: `/settings`, `/sources`

Добавить источник (в ЛС боту от Owner):

```text
/sources add <chat_identifier>
```

## 6) Обновление до новой версии

1. Остановить контейнер:
   ```bash
   docker compose down
   ```
2. Заменить файлы проекта на новые.
3. Поднять заново:
   ```bash
   docker compose up --build -d
   ```

## 7) Важные примечания

- Если `GROUP_ID` или `NEWS_THREAD_ID` не заданы — публикация блокируется, owner получит уведомление.
- База и telethon-сессия лежат в `./data` (смонтирован volume), поэтому сохраняются между перезапусками.
