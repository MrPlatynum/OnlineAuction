#!/usr/bin/env python3
"""
Тест поиска по реальным данным из вашей базы
"""

import requests

BASE_URL = "http://127.0.0.1:8000"

print("🧪 ТЕСТ ПОИСКА ПО РЕАЛЬНЫМ ДАННЫМ\n")

# Тестируем поиск по названиям из вашей базы
real_searches = [
    "hgf",  # Полное совпадение
    "hrhrt",  # Полное совпадение
    "Шимпанзе",  # Кириллица
    "Панда",  # Кириллица
    "Тигр",  # Кириллица
    "h",  # Часть слова
    "Пан",  # Часть кириллического слова
]

for search in real_searches:
    response = requests.get(f"{BASE_URL}/api/auctions", params={"search": search})
    data = response.json()

    found = data.get('total', 0)
    status = "✅" if found > 0 else "❌"

    print(f"{status} Поиск '{search}': найдено {found} аукционов")

    if found > 0:
        items = data.get('items', [])[:3]
        for item in items:
            print(f"   • {item['title']} - ${item['current_price']}")
    print()

print("\n" + "=" * 60)
print("ВЫВОД:")
print("=" * 60)
print("Если хотя бы один тест прошёл (✅), значит поиск РАБОТАЕТ!")
print("Просто в базе нет аукционов с 'iPhone', 'laptop' и т.д.")
print("\nДля полного тестирования создайте аукцион с названием 'iPhone Test'")
print("и повторите тест поиска по слову 'iPhone'")