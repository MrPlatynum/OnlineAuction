# Performance benchmark

Load test for measuring API throughput and latency.

## How it works

[`load_test.py`](load_test.py) запускает `--concurrency` async-воркеров,
которые делят один `httpx.AsyncClient` и шлют GET-запросы на выбранный
эндпоинт пока не наберут `--requests` штук. Печатает throughput (req/s)
и latency-перцентили (p50/p95/p99).

Перед измерением - короткий warm-up (5 запросов), чтобы первый
измеренный запрос не платил за TCP-handshake.

## Запуск

В одном терминале - сервер:

```bash
docker compose up -d
python -m alembic upgrade head
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

В другом - бенчмарк:

```bash
python benchmarks/load_test.py
```

По умолчанию: 1000 GET-запросов на `/api/auctions` с concurrency 50.
Можно переопределить:

```bash
python benchmarks/load_test.py --requests 5000 --concurrency 200 --endpoint /api/categories
```

## На что смотреть

- **Throughput (req/s)** - сколько запросов сервер обрабатывает в
  секунду. Async-стек выигрывает на высокой concurrency, потому что
  event loop не блокируется на ожидании ответа от Postgres.
- **p95 / p99 latency** - средняя latency скрывает «хвост»; именно
  хвостовые перцентили показывают как ведёт себя сервер под нагрузкой.

## Результаты (v0.3.0, эндпоинт `GET /api/auctions`)

Один процесс uvicorn, Postgres в Docker на той же машине, пул
SQLAlchemy `pool_size=10, max_overflow=20` (макс. 30 соединений к БД).

| Concurrency | Throughput | p50    | p95    | p99    | Errors |
| -----------:| ----------:| ------:| ------:| ------:| ------:|
| 50          | 167 req/s  | 248 ms | 658 ms | 1.0 s  | 0      |
| 100         | 173 req/s  | 482 ms | 1.3 s  | 2.9 s  | 0      |
| 200         | 121 req/s  | 1.0 s  | 6.0 s  | 8.0 s  | 0      |
| 500         | 58 req/s   | 8.1 s  | 18.2 s | 20.9 s | 128    |

До 100 одновременных пользователей - ~170 req/s без единой ошибки.
Дальше упор в пул соединений к Postgres: запросы выстраиваются в
очередь, p95 растёт. На 500 - таймауты. Пути расширения: увеличить
`max_overflow`, поднять `max_connections` в Postgres, либо запустить
несколько uvicorn-воркеров через gunicorn.
