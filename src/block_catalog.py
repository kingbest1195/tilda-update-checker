"""
Модуль мониторинга каталога блоков Tilda.

Загружает публичный каталог ~550 блоков с https://tilda.ru/page/tplslistjs/,
отслеживает изменения (новые блоки, удалённые, смена видимости testers→public),
опционально анализирует превью через Vision API.
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests

import config
from src.database import db, TildaBlock, BlockCatalogChange

logger = logging.getLogger(__name__)


class BlockCatalogMonitor:
    """Мониторинг каталога блоков Tilda"""

    # Поля, отслеживаемые для детекции изменений
    TRACKED_FIELDS = [
        'cod', 'block_type', 'title', 'descr', 'icon',
        'parent_tpl_id', 'whocansee', 'variation',
        'has_block_background', 'disable_for_plan0', 'fields'
    ]

    def fetch_catalog(self) -> Optional[List[dict]]:
        """
        Загрузить каталог блоков с tilda.ru.

        Returns:
            Список блоков (raw dict) или None при ошибке
        """
        url = f"{config.BLOCK_CATALOG_URL}?v={int(time.time())}"

        try:
            response = requests.get(
                url,
                headers={"User-Agent": config.USER_AGENT},
                timeout=config.REQUEST_TIMEOUT
            )
            response.raise_for_status()

            text = response.text

            # Парсинг: window.$tpls=[...];
            match = re.search(r'window\.\$tpls\s*=\s*(\[.*\])\s*;?', text, re.DOTALL)
            if not match:
                logger.error("Не удалось найти window.$tpls в ответе каталога")
                return None

            raw_json = match.group(1)
            blocks = json.loads(raw_json)

            logger.info(f"Каталог загружен: {len(blocks)} блоков")
            return blocks

        except requests.RequestException as e:
            logger.error(f"Ошибка загрузки каталога блоков: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON каталога: {e}")
            return None

    def _normalize_block(self, raw: dict) -> dict:
        """
        Маппинг полей из JSON каталога на поля БД.

        Args:
            raw: Сырой dict из каталога

        Returns:
            Нормализованный dict для TildaBlock
        """
        fields_raw = raw.get('fields')
        if isinstance(fields_raw, (dict, list)):
            fields_str = json.dumps(fields_raw, ensure_ascii=False)
        elif isinstance(fields_raw, str):
            fields_str = fields_raw
        else:
            fields_str = None

        return {
            'block_id': str(raw.get('id', '')),
            'cod': raw.get('cod', ''),
            'block_type': str(raw.get('type', '')),
            'title': raw.get('title', ''),
            'descr': raw.get('descr', ''),
            'icon': raw.get('icon', ''),
            'parent_tpl_id': str(raw.get('parenttplid', '')) if raw.get('parenttplid') else None,
            'whocansee': raw.get('whocansee', '') or '',
            'variation': 1 if raw.get('variation') else 0,
            'has_block_background': 1 if raw.get('hasblockbackground') else 0,
            'disable_for_plan0': 1 if raw.get('disableforplan0') else 0,
            'fields': fields_str,
        }

    def _compute_hash(self, block_data: dict) -> str:
        """Вычислить SHA-256 хеш для детекции изменений"""
        # Берём только отслеживаемые поля для хеша
        hash_data = {k: block_data.get(k) for k in self.TRACKED_FIELDS}
        raw = json.dumps(hash_data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def check_catalog(self) -> dict:
        """
        Основная функция проверки каталога блоков.

        Returns:
            dict с результатами: {
                'is_first_run': bool,
                'total_blocks': int,
                'new_blocks': List[dict],
                'removed_blocks': List[dict],
                'changed_blocks': List[dict],  # включая visibility_change
                'changes_saved': int
            }
        """
        result = {
            'is_first_run': False,
            'total_blocks': 0,
            'new_blocks': [],
            'removed_blocks': [],
            'changed_blocks': [],
            'changes_saved': 0,
        }

        # 1. Загрузить каталог
        raw_blocks = self.fetch_catalog()
        if raw_blocks is None:
            logger.error("Не удалось загрузить каталог блоков")
            return result

        result['total_blocks'] = len(raw_blocks)

        # 2. Нормализовать
        catalog = {}
        for raw in raw_blocks:
            norm = self._normalize_block(raw)
            norm['data_hash'] = self._compute_hash(norm)
            catalog[norm['block_id']] = norm

        # 3. Загрузить текущее состояние из БД
        existing_blocks = db.get_all_blocks()
        existing_map = {b.block_id: b for b in existing_blocks}

        # Определить первый запуск
        is_first_run = len(existing_blocks) == 0
        result['is_first_run'] = is_first_run

        if is_first_run:
            logger.info(f"Первый запуск: сохранение базового снимка ({len(catalog)} блоков)")

        # 4. Найти новые блоки
        for block_id, block_data in catalog.items():
            if block_id not in existing_map:
                # Новый блок
                db.save_block(block_data)

                if not is_first_run:
                    change_data = {
                        'block_id': block_id,
                        'cod': block_data['cod'],
                        'change_type': 'new_block',
                        'new_value': block_data.get('whocansee', ''),
                    }

                    # LLM-анализ превью для нового блока
                    llm_text = self._get_block_analysis(block_data)
                    if llm_text:
                        change_data['llm_analysis'] = llm_text

                    db.save_block_change(change_data)
                    result['new_blocks'].append(block_data)
                    result['changes_saved'] += 1

                    visibility = "бета" if block_data.get('whocansee') == 'testers' else "публичный"
                    logger.info(f"Новый блок: {block_data['cod']} — {block_data['title']} ({visibility})")

            else:
                # Существующий блок — проверить изменения
                existing = existing_map[block_id]

                if block_data['data_hash'] != existing.data_hash:
                    # Есть изменения — определить какие
                    changes_for_block = self._detect_field_changes(existing, block_data)

                    for change in changes_for_block:
                        db.save_block_change(change)
                        result['changes_saved'] += 1

                    if changes_for_block:
                        result['changed_blocks'].append({
                            'block_data': block_data,
                            'changes': changes_for_block,
                        })

                    # Обновить блок в БД
                    block_data['last_changed_at'] = datetime.utcnow()
                    db.save_block(block_data)
                else:
                    # Без изменений — обновить last_seen_at
                    db.save_block({
                        'block_id': block_id,
                        'last_seen_at': datetime.utcnow(),
                    })

        # 5. Найти удалённые блоки
        catalog_ids = set(catalog.keys())
        for block_id, existing in existing_map.items():
            if block_id not in catalog_ids and existing.is_removed == 0:
                db.mark_block_removed(block_id)

                if not is_first_run:
                    change_data = {
                        'block_id': block_id,
                        'cod': existing.cod,
                        'change_type': 'removed_block',
                        'old_value': existing.title,
                    }
                    db.save_block_change(change_data)
                    result['removed_blocks'].append({
                        'block_id': block_id,
                        'cod': existing.cod,
                        'title': existing.title,
                    })
                    result['changes_saved'] += 1
                    logger.info(f"Блок удалён: {existing.cod} — {existing.title}")

        # Итого
        if is_first_run:
            logger.info(f"Базовый снимок сохранён: {len(catalog)} блоков")
        else:
            logger.info(
                f"Проверка каталога завершена: "
                f"{len(result['new_blocks'])} новых, "
                f"{len(result['removed_blocks'])} удалённых, "
                f"{len(result['changed_blocks'])} изменённых"
            )

        return result

    def _detect_field_changes(self, existing: TildaBlock, new_data: dict) -> List[dict]:
        """Определить какие поля изменились"""
        changes = []

        for field in self.TRACKED_FIELDS:
            old_val = getattr(existing, field, None)
            new_val = new_data.get(field)

            # Нормализация для сравнения
            if old_val is None:
                old_val = ''
            if new_val is None:
                new_val = ''

            old_str = str(old_val)
            new_str = str(new_val)

            if old_str != new_str:
                # Определить тип изменения
                if field == 'whocansee':
                    change_type = 'visibility_change'
                else:
                    change_type = 'field_change'

                change_data = {
                    'block_id': existing.block_id,
                    'cod': new_data.get('cod', existing.cod),
                    'change_type': change_type,
                    'field_name': field,
                    'old_value': old_str,
                    'new_value': new_str,
                }

                # LLM-анализ для visibility_change (testers → "")
                if change_type == 'visibility_change' and old_str == 'testers' and new_str == '':
                    llm_text = self._get_block_analysis(new_data)
                    if llm_text:
                        change_data['llm_analysis'] = llm_text

                changes.append(change_data)

                if change_type == 'visibility_change':
                    logger.info(
                        f"Смена видимости блока {existing.cod}: "
                        f"'{old_str}' → '{new_str}'"
                    )

        return changes

    def _get_block_analysis(self, block_data: dict) -> Optional[str]:
        """Получить LLM-анализ превью блока, если доступен"""
        try:
            from src.llm_analyzer import analyzer

            analysis = analyzer.analyze_block_preview(block_data)
            if analysis:
                return json.dumps(analysis, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"LLM-анализ превью недоступен: {e}")

        return None

    def print_catalog(self):
        """Вывести каталог блоков из БД"""
        blocks = db.get_all_blocks()

        if not blocks:
            print("\nКаталог блоков пуст. Запустите --check-blocks для загрузки.")
            return

        active = [b for b in blocks if b.is_removed == 0]
        removed = [b for b in blocks if b.is_removed == 1]
        beta = [b for b in active if b.whocansee == 'testers']
        public = [b for b in active if b.whocansee != 'testers']

        print(f"\n{'='*80}")
        print(f"КАТАЛОГ БЛОКОВ TILDA")
        print(f"{'='*80}")
        print(f"Всего: {len(blocks)} | Активных: {len(active)} | "
              f"Публичных: {len(public)} | Бета: {len(beta)} | Удалённых: {len(removed)}")
        print(f"{'='*80}")

        # Группировка по типу
        by_type: Dict[str, list] = {}
        for b in active:
            t = b.block_type or 'unknown'
            by_type.setdefault(t, []).append(b)

        for block_type in sorted(by_type.keys()):
            type_blocks = by_type[block_type]
            print(f"\n  Тип {block_type} ({len(type_blocks)} блоков):")
            for b in sorted(type_blocks, key=lambda x: x.cod or ''):
                status = " [БЕТА]" if b.whocansee == 'testers' else ""
                print(f"    {b.cod:10s} {b.title or 'N/A':40s}{status}")

        print()

    def print_changes_report(self, result: dict = None, limit: int = 50):
        """Вывести отчёт об изменениях"""
        if result:
            # Отчёт о только что проведённой проверке
            print(f"\n{'='*80}")
            print(f"РЕЗУЛЬТАТЫ ПРОВЕРКИ КАТАЛОГА БЛОКОВ")
            print(f"{'='*80}")

            if result.get('is_first_run'):
                print(f"Первый запуск: сохранён базовый снимок ({result['total_blocks']} блоков)")
                print("При следующей проверке будут отслеживаться изменения.")
                return

            print(f"Всего блоков в каталоге: {result['total_blocks']}")

            if result['new_blocks']:
                print(f"\n  Новые блоки ({len(result['new_blocks'])}):")
                for b in result['new_blocks']:
                    vis = " [БЕТА]" if b.get('whocansee') == 'testers' else ""
                    print(f"    + {b['cod']:10s} {b['title']}{vis}")

            if result['removed_blocks']:
                print(f"\n  Удалённые блоки ({len(result['removed_blocks'])}):")
                for b in result['removed_blocks']:
                    print(f"    - {b['cod']:10s} {b['title']}")

            if result['changed_blocks']:
                print(f"\n  Изменённые блоки ({len(result['changed_blocks'])}):")
                for item in result['changed_blocks']:
                    bd = item['block_data']
                    print(f"    ~ {bd['cod']:10s} {bd['title']}")
                    for ch in item['changes']:
                        if ch['change_type'] == 'visibility_change':
                            print(f"        Видимость: '{ch['old_value']}' → '{ch['new_value']}'")
                        else:
                            print(f"        {ch['field_name']}: '{ch.get('old_value', '')[:30]}' → '{ch.get('new_value', '')[:30]}'")

            if not result['new_blocks'] and not result['removed_blocks'] and not result['changed_blocks']:
                print("\n  Изменений не обнаружено.")

            print()
            return

        # Отчёт из БД (для --show-block-changes)
        changes = db.get_recent_block_changes(limit=limit)

        if not changes:
            print("\nИстория изменений каталога блоков пуста.")
            return

        print(f"\n{'='*80}")
        print(f"ПОСЛЕДНИЕ ИЗМЕНЕНИЯ КАТАЛОГА БЛОКОВ ({len(changes)})")
        print(f"{'='*80}")

        for ch in changes:
            ts = ch.detected_at.strftime('%Y-%m-%d %H:%M') if ch.detected_at else 'N/A'
            tg_icon = "✅" if ch.telegram_sent else "⏳"

            if ch.change_type == 'new_block':
                vis = " [БЕТА]" if ch.new_value == 'testers' else ""
                print(f"  {ts} {tg_icon} + Новый блок: {ch.cod}{vis}")
            elif ch.change_type == 'removed_block':
                print(f"  {ts} {tg_icon} - Удалён: {ch.cod} ({ch.old_value})")
            elif ch.change_type == 'visibility_change':
                print(f"  {ts} {tg_icon} ~ Видимость {ch.cod}: '{ch.old_value}' → '{ch.new_value}'")
            else:
                print(f"  {ts} {tg_icon} ~ {ch.cod}: {ch.field_name} изменено")

            # Показать LLM-анализ если есть
            if ch.llm_analysis:
                try:
                    analysis = json.loads(ch.llm_analysis)
                    summary = analysis.get('summary', '')
                    if summary:
                        print(f"        LLM: {summary[:100]}")
                except (json.JSONDecodeError, AttributeError):
                    pass

        print()


# Глобальный экземпляр
block_monitor = BlockCatalogMonitor()
