# Gemini Transcription — Integration Requirements

## Prototype status

`transcribe.py` — рабочий standalone-скрипт. Проверено на реальном видео (45 MB, 6 min).
- Модель: настраивается через `GEMINI_MODEL` (по умолчанию `gemini-2.5-flash`, free tier: 5 RPM, 250K TPM, 20 RPD)
- Пакет: `google-genai`
- Промпты: `meeting-transcripts/prompts/transcription_prompt.txt`, `meeting-transcripts/prompts/title_prompt.txt` (примеры в `prompts_examples/`)
- Ретраи: 3 попытки с задержками 15s, 45s, 90s

## Новый пайплайн

**Было:** Download → Upload → Discord notify

**Стало:** Download → Upload → Transcribe → Generate title → Save transcript (git push) → Discord notify

## Шаги интеграции

### 1. `transcription_client.py` (новый файл)

Обёртка над Gemini API для использования из `main.py`.

```python
def transcribe_video(video_path: str, duration_seconds: int = 0) -> str | None
```

- Если `duration_seconds > MAX_TRANSCRIPTION_DURATION` (7200s = 2 часа) — возвращает `None` и логирует причину
- Загружает видео в Gemini Files API
- Ждёт завершения обработки (`state == "PROCESSING"`)
- Отправляет запрос на транскрипцию с промптом из `TRANSCRIPTION_PROMPT_PATH`
- Удаляет файл из Gemini после получения результата
- Ретраи через `retry_with_backoff` (15s, 45s, 90s)
- При ошибке возвращает `None` (не бросает исключение)

```python
def generate_title(transcript: str) -> str | None
```

- Читает промпт из `TITLE_PROMPT_PATH`, приклеивает транскрипт в конец
- Отправляет в Gemini, получает короткое название (5-7 слов)
- Возвращает строку-название или `None` при ошибке
- Ретраи через `retry_with_backoff` (5s, 10s, 20s)

### 2. Transcript storage (git repo)

Отдельный GitHub-репозиторий для хранения транскриптов.

Структура файлов в репозитории:
```
2026-02-23 16-53 - Баланс кошельков и аналитика.txt
2026-02-24 12-00 - Стендап по ML-моделям.txt
```

Формат: `{date} {time} - {generated_title}.txt` — дата и время как в папках с видео, название — от Gemini. Если Gemini не сгенерировал название, используем topic из Zoom (как сейчас).

В `main.py`:
- Сохранить транскрипт в файл в локальном клоне репозитория
- `git add` + `git commit` + `git push`
- Сформировать URL файла на GitHub для Discord-уведомления

Конфигурация в `.env`:
```
TRANSCRIPTS_REPO_PATH=./transcripts
TRANSCRIPTS_GITHUB_REPO=user/zoom-transcripts  # для формирования URL
```

### 3. Изменения в `main.py`

Новые шаги между Upload и Discord notify:

```
# Step 3: Transcribe (if not already transcribed)
if not existing_record or not existing_record.get('transcribed_at'):
    transcript = transcription_client.transcribe_video(file_path, duration_seconds)
    if transcript:
        title = transcription_client.generate_title(transcript)
        transcript_url = save_transcript(transcript, ...)
        tracker.record_transcription(zoom_uuid, transcript_url, title)
    else:
        logger.warning("Transcription skipped or failed, continuing without transcript")

# Step 4: Discord notify (updated)
```

Транскрипция пропускается если:
- Видео длиннее 2 часов (`MAX_TRANSCRIPTION_DURATION`)
- Gemini вернул ошибку после ретраев

В обоих случаях — **продолжаем без транскрипта**, не блокируем нотификацию.

### 4. Изменения в `discord_client.py`

Обновить `send_notification`:

```python
def send_notification(
    youtube_url: str,
    transcript_url: str | None = None,
    generated_title: str | None = None
) -> bool
```

Формат сообщения:
```
📹 **Стендап про баланс кошельков**    ← generated_title (если есть)
🎬 https://youtube.com/watch?v=...
📝 https://github.com/user/repo/blob/main/2026-02-23_Стендап.txt  ← если есть
```

Если нет транскрипта — текущий формат (только YouTube URL).

### 5. Изменения в `video_tracker.py`

Новые поля в CSV:
```
"transcribed_at"     — когда транскрипт готов
"transcript_url"     — ссылка на GitHub
"generated_title"    — название от Gemini
```

Новый метод:
```python
def record_transcription(self, zoom_uuid: str, transcript_url: str, generated_title: str = '') -> None
```

Обновить `is_processed()` — считать запись обработанной без `transcribed_at` (транскрипция опциональна).

### 6. Изменения в `config.py`

```python
GEMINI_API_KEY = get_env("GEMINI_API_KEY")
GEMINI_MODEL = get_env("GEMINI_MODEL", "gemini-2.5-flash")
TRANSCRIPTION_PROMPT_PATH = Path(get_env("TRANSCRIPTION_PROMPT_PATH", "./meeting-transcripts/prompts/transcription_prompt.txt")).resolve()
TITLE_PROMPT_PATH = Path(get_env("TITLE_PROMPT_PATH", "./meeting-transcripts/prompts/title_prompt.txt")).resolve()
TRANSCRIPTS_REPO_PATH = Path(get_env("TRANSCRIPTS_REPO_PATH", "./transcripts")).resolve()
TRANSCRIPTS_GITHUB_REPO = get_env("TRANSCRIPTS_GITHUB_REPO", "")
MAX_TRANSCRIPTION_DURATION = int(get_env("MAX_TRANSCRIPTION_DURATION", "7200"))  # 2 hours
```

### 7. Зависимости

Добавить в `requirements.txt`:
```
google-genai
```

Добавить в `.env.example`:
```
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
TRANSCRIPTION_PROMPT_PATH=./meeting-transcripts/prompts/transcription_prompt.txt
TITLE_PROMPT_PATH=./meeting-transcripts/prompts/title_prompt.txt
TRANSCRIPTS_REPO_PATH=./transcripts
TRANSCRIPTS_GITHUB_REPO=user/zoom-transcripts
MAX_TRANSCRIPTION_DURATION=7200
```

## Graceful degradation

| Что зафейлилось | Поведение |
|---|---|
| Видео > 2 часов | Транскрипция пропускается, в Discord-нотификации указано "Транскрипт: видео слишком длинное" |
| Транскрипция (Gemini) | Видео выкладывается, Discord-нотификация без транскрипта и без сгенерированного названия |
| Генерация названия | Транскрипт сохраняется, в Discord — без названия |
| Git push транскрипта | Транскрипт сохранён локально, Discord-нотификация без ссылки на транскрипт |
| Всё вместе | Пайплайн работает как раньше: YouTube URL в Discord |

## Ограничения free tier Gemini

- 20 запросов в день (RPD) — при 5 встречах в день хватит на транскрипцию + генерацию названия
- Максимальный размер файла: 2 GB
- Файл живёт 48 часов в Gemini Files API (удаляем сразу после использования)
