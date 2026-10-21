# ReelTrack Studio

Локальное приложение для распознавания музыки из Instagram Reels, поиска полных версий и ведения музыкальной библиотеки.

Интерфейс: Next.js, Tailwind CSS, Framer Motion и shadcn/ui. API и обработка: FastAPI и Python.

## Возможности

- Добавление и обработка ссылок на Reels
- Распознавание песен через Shazam
- Поиск полных версий и загрузка MP3
- Медиатека, поиск, фильтры, прослушивание и экспорт результатов

## Требования

- Node.js 20.9 или новее
- pnpm
- Python 3.13 или новее
- FFmpeg и ffprobe

Установи системные зависимости для своей ОС:

- **CachyOS / Arch Linux:** `sudo pacman -S nodejs pnpm python ffmpeg`
- **macOS:** Node.js, pnpm и Python; FFmpeg — `brew install ffmpeg`
- **Windows:** Node.js, pnpm, Python с Python Launcher и FFmpeg. Убедись, что `ffmpeg` и `ffprobe` доступны через `PATH`.

## Первый запуск

Выполни команды из корневой папки проекта:

```bash
pnpm install
pnpm setup:python
pnpm dev
```

`pnpm setup:python` создаёт виртуальное окружение `backend/.venv` и устанавливает зависимости API.

Открой <http://127.0.0.1:3000>. Чтобы остановить приложение и освободить порты, нажми `Ctrl+C`.

## Последующие запуски

Из корневой папки проекта:

```bash
pnpm dev
```

Если зависимости Python изменились, повтори `pnpm setup:python`.

## Данные

Ссылки, CSV-отчёты, экспорты и MP3 хранятся в `backend/engine/`. Эти файлы не добавляются в Git.

Приложение предназначено для локального использования. Не открывай API в публичную сеть без настройки авторизации и защиты.
