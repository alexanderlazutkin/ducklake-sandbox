# DuckLake Sandbox

Песочница для работы с **DuckLake** — каталогом данных на базе DuckDB с хранением данных в MinIO (S3-совместимое хранилище). Проект основан на [ducklake-bootstrap](https://github.com/hotdata-dev/ducklake-bootstrap).

## Содержание

- [Возможности](#возможности)
- [Требования](#требования)
- [Быстрый старт](#быстрый-старт)
- [Конфигурация](#конфигурация)
- [CLI команды](#cli-команды)
  - [bootstrap_ducklake.py](#bootstrap_ducklakepy)
  - [run_tpch_queries.py](#run_tpch_queriespy)
- [Структура проекта](#структура-проекта)
- [Примеры использования](#примеры-использования)

## Возможности

- 🚀 Автоматическое развёртывание DuckLake с метаданными в DuckDB и данными в MinIO
- 📊 Генерация и загрузка TPC-H данных с настраиваемым scale factor
- 🔄 Возможность полного пересоздания каталога и данных
- ⏱️ Бенчмаркинг запросов с многократными итерациями
- 📈 Сравнение производительности DuckLake vs локальной DuckDB
- 💾 Сохранение всех SQL-запросов и результатов валидации

## Требования

- Python 3.9+
- Docker (для MinIO)
- Зависимости Python:
  ```bash
  pip install duckdb pyyaml minio pandas
  ```

## Быстрый старт

### Автоматический запуск

```bash
# Установка зависимостей и настройка окружения
./setup_env.sh

# Полный цикл: запуск MinIO, создание бакета, загрузка TPC-H данных
./run_ducklake.sh
```

### Ручной запуск

1. **Запуск MinIO**

```bash
docker compose -f docker-compose.minio.yml up -d
# Консоль MinIO: http://localhost:9001
# S3 endpoint: http://localhost:9000
# Учётные данные по умолчанию: minioadmin / minioadmin
```

2. **Создание конфигурации**

```bash
cp config.example.yaml config.yaml
# Отредактируйте config.yaml при необходимости
```

3. **Создание бакета и загрузка данных**

```bash
# Создать бакет в MinIO
python bootstrap_ducklake.py ensure-bucket --config config.yaml

# Подключить DuckLake
python bootstrap_ducklake.py attach --config config.yaml

# Загрузить TPC-H данные (scale factor = 1)
python bootstrap_ducklake.py load-tpch --config config.yaml --scale 1
```

## Конфигурация

Пример файла `config.yaml`:

```yaml
metadata:
  duckdb_file: "./metadata.ducklake"

storage:
  bucket: "dlsandbox"
  prefix: "tpch/"
  endpoint: "http://localhost:9000"
  region: "eu-central-1"
  use_ssl: false
  url_style: "path"
  access_key: "minioadmin"      # или через env MINIO_ACCESS_KEY
  secret_key: "minioadmin"      # или через env MINIO_SECRET_KEY

catalog:
  alias: "dlsandbox"

tpch:
  default_scale: 1
```

## CLI команды

### bootstrap_ducklake.py

Скрипт для управления DuckLake каталогом и загрузки данных.

#### init-config

Создать файл конфигурации по умолчанию:

```bash
python bootstrap_ducklake.py init-config [--path config.yaml] [--force]
```

#### ensure-bucket

Создать бакет в MinIO, если не существует:

```bash
python bootstrap_ducklake.py ensure-bucket --config config.yaml
```

#### attach

Подключить DuckLake каталог:

```bash
python bootstrap_ducklake.py attach --config config.yaml
```

#### load-tpch

Сгенерировать и загрузить TPC-H данные в DuckLake:

```bash
python bootstrap_ducklake.py load-tpch [OPTIONS]

OPTIONS:
  --config PATH       Путь к файлу конфигурации (по умолчанию: config.yaml)
  --scale INT         Scale factor TPC-H (переопределяет config)
  --local-db PATH     Путь к локальному файлу DuckDB (по умолчанию: tpch-sf{scale}.duckdb)
  --reset             Пересоздать каталог: удалить метаданные и очистить бакет

ПРИМЕРЫ:
  # Загрузка с scale factor 1
  python bootstrap_ducklake.py load-tpch --scale 1

  # Загрузка с указанием пути к локальной базе
  python bootstrap_ducklake.py load-tpch --scale 1 --local-db /data/tpch.duckdb

  # Полное пересоздание каталога
  python bootstrap_ducklake.py load-tpch --scale 1 --reset
```

### run_tpch_queries.py

Скрипт для валидации и бенчмаркинга TPC-H запросов.

#### Режим валидации

Сравнивает результаты запросов между DuckLake и локальной DuckDB:

```bash
python run_tpch_queries.py [OPTIONS]

OPTIONS:
  --config PATH       Путь к файлу конфигурации (по умолчанию: config.yaml)
  --scale INT         Scale factor TPC-H
  --queries LIST      Список запросов через запятую (например: "1,3,5")
  --output DIR        Директория для результатов (по умолчанию: tpch_validation)
  --no-save-queries   Не сохранять SQL-запросы в файл
```

#### Режим бенчмарка

Измеряет время выполнения запросов:

```bash
python run_tpch_queries.py --benchmark [OPTIONS]

OPTIONS:
  --benchmark         Включить режим бенчмарка
  --target TARGET     Целевая база: "ducklake" или "duckdb" (по умолчанию: ducklake)
  --local-db PATH     Путь к локальной DuckDB (для --target duckdb)
  --iterations, -n N  Количество итераций каждого запроса (по умолчанию: 1)
  --output DIR        Директория для результатов (по умолчанию: tpch_benchmark)

ПРИМЕРЫ:
  # Бенчмарк DuckLake с 3 итерациями
  python run_tpch_queries.py --benchmark --target ducklake -n 3

  # Бенчмарк локальной DuckDB
  python run_tpch_queries.py --benchmark --target duckdb -n 3

  # Сравнение производительности
  python run_tpch_queries.py --benchmark --target duckdb -n 3 --output bench_duckdb
  python run_tpch_queries.py --benchmark --target ducklake -n 3 --output bench_ducklake

  # Только определённые запросы
  python run_tpch_queries.py --benchmark --queries "1,3,5,10" -n 5
```

#### Выходные файлы

| Файл | Описание |
|------|----------|
| `benchmark_detailed_timing.csv` | Время каждой попытки каждого запроса |
| `benchmark_summary.csv` | Агрегированные данные: среднее, мин, макс время |
| `tpch_all_queries.sql` | Все SQL-запросы TPC-H |
| `validation_summary.csv` | Результаты валидации |
| `query_timing.csv` | Время выполнения запросов при валидации |

## Структура проекта

```
ducklake-sandbox/
├── bootstrap_ducklake.py    # CLI для управления DuckLake
├── run_tpch_queries.py      # CLI для валидации и бенчмаркинга
├── config.example.yaml      # Пример конфигурации
├── config.yaml              # Конфигурация (создаётся пользователем)
├── docker-compose.minio.yml # Docker Compose для MinIO
├── requirements.txt         # Зависимости Python
├── setup_env.sh            # Скрипт настройки окружения
├── run_ducklake.sh         # Скрипт полного цикла запуска
├── metadata.ducklake       # Файл метаданных DuckDB (создаётся автоматически)
├── tpch-sf*.duckdb         # Локальные базы TPC-H (создаются автоматически)
└── tpch_*/                 # Директории с результатами
```

## Примеры использования

### Полный цикл работы

```bash
# 1. Запуск MinIO
docker compose -f docker-compose.minio.yml up -d

# 2. Настройка
cp config.example.yaml config.yaml
python bootstrap_ducklake.py ensure-bucket

# 3. Загрузка данных TPC-H (scale factor = 1)
python bootstrap_ducklake.py load-tpch --scale 1

# 4. Валидация данных
python run_tpch_queries.py

# 5. Бенчмарк DuckLake
python run_tpch_queries.py --benchmark --target ducklake -n 3

# 6. Бенчмарк локальной DuckDB для сравнения
python run_tpch_queries.py --benchmark --target duckdb -n 3
```

### Пересоздание каталога

```bash
# Удалить метаданные, очистить бакет и загрузить данные заново
python bootstrap_ducklake.py load-tpch --scale 1 --reset
```

### Работа с разными scale factor

```bash
# Scale factor 0.1 (маленький набор для тестирования)
python bootstrap_ducklake.py load-tpch --scale 0.1

# Scale factor 10 (большой набор)
python bootstrap_ducklake.py load-tpch --scale 10 --local-db tpch-sf10.duckdb
```

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                      DuckDB (in-memory)                      │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    DuckLake Extension                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                           │                                   │
│           ┌───────────────┴───────────────┐                   │
│           ▼                               ▼                   │
│  ┌─────────────────┐            ┌─────────────────┐          │
│  │  metadata.duck  │            │   MinIO (S3)    │          │
│  │   (catalog)     │            │  (data files)   │          │
│  │                 │            │                 │          │
│  │  - tables       │            │  - Parquet      │          │
│  │  - columns      │            │  - snapshots    │          │
│  │  - snapshots    │            │                 │          │
│  └─────────────────┘            └─────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## Лицензия

MIT License
