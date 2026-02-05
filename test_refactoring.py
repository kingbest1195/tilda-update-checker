#!/usr/bin/env python3
"""
Тестовый скрипт для демонстрации улучшений рефакторинга LLM-анализатора
"""
import sys
sys.path.insert(0, '/Users/putiniye/Library/Mobile Documents/com~apple~CloudDocs/Documents/tilda-update-checker')

from src.diff_detector import detector

# Тестовый минифицированный код (старая версия)
old_code = """function cart(){var items=[];this.add=function(item){items.push(item);};this.remove=function(id){items=items.filter(function(i){return i.id!==id;});};this.getTotal=function(){return items.reduce(function(sum,i){return sum+i.price;},0);};}function checkout(){console.log('checkout');}"""

# Тестовый минифицированный код (новая версия с изменениями)
new_code = """function cart(){var items=[];this.add=function(item){items.push(item);console.log('Item added:',item);};this.remove=function(id){items=items.filter(function(i){return i.id!==id;});};this.getTotal=function(){return items.reduce(function(sum,i){return sum+i.price;},0);};this.validatePromo=function(code){if(!code||code.length<3){return false;}return true;};}function checkout(){console.log('checkout');if(cart.items.length===0){alert('Cart is empty');return false;}}function newFeature(){console.log('new');}"""

print("=" * 80)
print("ТЕСТ 1: Beautify минифицированного кода")
print("=" * 80)

# Демонстрация beautify
beautified_old = detector._beautify_code(old_code, 'js')
beautified_new = detector._beautify_code(new_code, 'js')

print(f"\n📊 Статистика:")
print(f"  Старый код: {len(old_code.splitlines())} строк (минифицирован)")
print(f"  Новый код: {len(new_code.splitlines())} строк (минифицирован)")
print(f"  После beautify старый: {len(beautified_old.splitlines())} строк")
print(f"  После beautify новый: {len(beautified_new.splitlines())} строк")

print(f"\n📝 Пример beautified кода (первые 15 строк новой версии):")
print("-" * 80)
for i, line in enumerate(beautified_new.splitlines()[:15], 1):
    print(f"{i:3d}: {line}")
print("-" * 80)

print("\n" + "=" * 80)
print("ТЕСТ 2: Анализ изменений с beautify")
print("=" * 80)

# Анализ изменений
change_info = detector._analyze_change(
    old_code,
    new_code,
    len(old_code),
    len(new_code),
    'js'
)

print(f"\n📊 Результаты анализа:")
print(f"  Размер изменения: {change_info['stats']['size_diff']} байт ({change_info['change_percent']}%)")
print(f"  Добавлено строк: {change_info['stats']['added_lines']}")
print(f"  Удалено строк: {change_info['stats']['removed_lines']}")
print(f"  Всего изменений: {change_info['stats']['total_changes']}")
print(f"  Значимое изменение: {'Да' if change_info['is_significant'] else 'Нет'}")
print(f"  Строк в diff: {len(change_info['diff_lines'])}")

print("\n" + "=" * 80)
print("ТЕСТ 3: Извлечение метаданных из diff")
print("=" * 80)

# Извлечение метаданных
metadata = detector._extract_diff_metadata(change_info['diff_lines'])

print(f"\n🔍 Обнаруженные метаданные:")
print(f"  Добавленные функции: {metadata['added_functions']}")
print(f"  Удалённые функции: {metadata['removed_functions']}")
print(f"  Изменённые функции: {metadata['modified_functions']}")
print(f"  Новые зависимости: {len(metadata['new_imports'])} шт.")
print(f"  Изменения логики: {len(metadata['condition_changes'])} условий")

print("\n" + "=" * 80)
print("ТЕСТ 4: Подготовка контекста для LLM")
print("=" * 80)

# Подготовить контекст для LLM
test_change_info = {
    'url': 'https://static.tildacdn.com/js/tilda-cart-1.1.min.js',
    'file_type': 'js',
    'category': 'ecommerce',
    'priority': 'HIGH',
    'size_diff': len(new_code) - len(old_code),
    'change_percent': change_info['change_percent'],
    'stats': change_info['stats'],
    'diff_lines': change_info['diff_lines']
}

llm_context = detector.prepare_llm_context(test_change_info, max_tokens=10000)

print(f"\n📝 Контекст для LLM ({len(llm_context)} символов, ~{len(llm_context)//4} токенов):")
print("-" * 80)
print(llm_context[:1500])  # Первые 1500 символов
print("\n... (обрезано для читаемости) ...\n")
print("-" * 80)

print("\n" + "=" * 80)
print("ТЕСТ 5: Fallback анализ с метаданными")
print("=" * 80)

# Имитация fallback анализа
from src.llm_analyzer import analyzer

# Создать fallback анализ
fallback_analysis = analyzer._create_default_analysis(test_change_info)

print(f"\n📊 Fallback анализ (без LLM):")
print(f"  Тип изменения: {fallback_analysis['change_type']}")
print(f"  Severity: {fallback_analysis['severity']}")
print(f"  Описание: {fallback_analysis['description']}")
print(f"  Влияние: {fallback_analysis['user_impact']}")
print(f"  Рекомендации: {fallback_analysis['recommendations']}")

print("\n" + "=" * 80)
print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
print("=" * 80)

print(f"\n🎯 Ключевые улучшения:")
print(f"  1. Beautify увеличил читаемость с 1 до {len(beautified_new.splitlines())} строк")
print(f"  2. Извлечено {len(metadata['added_functions'])} новых функций из diff")
print(f"  3. Обнаружено {len(metadata['modified_functions'])} изменённых функций")
print(f"  4. Fallback анализ теперь содержит конкретные детали")
print(f"  5. LLM получает {len(change_info['diff_lines'])} строк контекста (было ~3)")
