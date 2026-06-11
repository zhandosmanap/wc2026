"""
Скрипт автоматически получает турнирные таблицы с championat.com
и обновляет файл tournament.json в репозитории.

Запускается через GitHub Actions каждые 30 минут.
"""

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.championat.com/football/_worldcup/tournament/6858/table/"

# Перевод русских названий команд в английские (для совпадения с bets.json)
NAME_MAP = {
    "Испания": "Spain",
    "Франция": "France",
    "Аргентина": "Argentina",
    "Португалия": "Portugal",
    "Швейцария": "Switzerland",
    "Англия": "England",
    "Бразилия": "Brazil",
    "Нидерланды": "Netherlands",
    "США": "USA",
    "Мексика": "Mexico",
    "Канада": "Canada",
    "Германия": "Germany",
    "Бельгия": "Belgium",
    "Хорватия": "Croatia",
    "Япония": "Japan",
    "Сенегал": "Senegal",
    "Марокко": "Morocco",
    "Сербия": "Serbia",
    "Польша": "Poland",
    "Дания": "Denmark",
    "Уругвай": "Uruguay",
    "Колумбия": "Colombia",
    "Чили": "Chile",
    "Перу": "Peru",
    "Эквадор": "Ecuador",
    "Венесуэла": "Venezuela",
    "Боливия": "Bolivia",
    "Панама": "Panama",
    "Коста-Рика": "Costa Rica",
    "Ямайка": "Jamaica",
    "Гондурас": "Honduras",
    "Гватемала": "Guatemala",
    "Гаити": "Haiti",
    "Южная Корея": "South Korea",
    "Австралия": "Australia",
    "Новая Зеландия": "New Zealand",
    "Саудовская Аравия": "Saudi Arabia",
    "Иран": "Iran",
    "Турция": "Turkey",
    "Украина": "Ukraine",
    "Чехия": "Czech Republic",
    "Южная Африка": "South Africa",
    "Камерун": "Cameroon",
    "Кот-д'Ивуар": "Ivory Coast",
    "ДР Конго": "DR Congo",
    "Кения": "Kenya",
    "Филиппины": "Philippines",
    "Катар": "Qatar",
    "Босния и Герцеговина": "Bosnia and Herzegovina",
    "Албания": "Albania",
    "Словения": "Slovenia",
    "Словакия": "Slovakia",
    "Румыния": "Romania",
    "Венгрия": "Hungary",
    "Греция": "Greece",
    "Австрия": "Austria",
    "Тунис": "Tunisia",
    "Нигерия": "Nigeria",
    "Гана": "Ghana",
    "Египет": "Egypt",
    "Алжир": "Algeria",
    "Индонезия": "Indonesia",
    "Узбекистан": "Uzbekistan",
    "Ирак": "Iraq",
    "Иордания": "Jordan",
    "Парагвай": "Paraguay",
    "Куба": "Cuba",
}


def to_en(name: str) -> str:
    """Переводит название команды с русского на английский."""
    name = name.strip()
    return NAME_MAP.get(name, name)


def safe_int(text: str) -> int:
    """Безопасно парсит число из текста ячейки."""
    try:
        return int(re.sub(r"[^\d]", "", text.strip()) or "0")
    except ValueError:
        return 0


def parse_goals(text: str):
    """
    Разбирает строку голов вида '3:1' или '3-1' на забитые и пропущенные.
    Возвращает (gf, ga).
    """
    m = re.search(r"(\d+)\D+(\d+)", text.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def fetch_html() -> str:
    """Загружает HTML страницы с заголовками реального браузера."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_groups(html: str) -> dict:
    """
    Ищет в HTML таблицы групп ЧМ и возвращает словарь вида:
    { "A": { "teams": [...] }, "B": {...}, ... }
    """
    soup = BeautifulSoup(html, "html.parser")
    groups = {}

    # Ищем заголовки вида "Группа A" / "Группа B" / "Group A" и т.п.
    group_pattern = re.compile(r"Групп[аa]\s*([A-L])", re.IGNORECASE)

    # Собираем все элементы, в тексте которых есть "Группа X"
    headers = []
    for tag in soup.find_all(True):
        if tag.name in ("h1", "h2", "h3", "h4", "h5", "div", "span", "td", "th"):
            text = tag.get_text(strip=True)
            m = group_pattern.search(text)
            # Проверяем, что элемент не вложен в другой элемент с тем же текстом
            if m and len(text) < 30:
                headers.append((tag, m.group(1).upper()))

    for header_tag, letter in headers:
        # Ищем ближайшую таблицу после заголовка
        table = None
        for sibling in header_tag.next_elements:
            if getattr(sibling, "name", None) == "table":
                table = sibling
                break

        if table is None:
            # Таблица может быть в родительском блоке
            parent = header_tag.find_parent(["div", "section", "article"])
            if parent:
                table = parent.find("table")

        if table is None:
            continue

        teams = []
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # Ищем ячейку с названием команды (содержит ссылку или текст с буквами)
            name_cell = None
            for cell in cells:
                text = cell.get_text(strip=True)
                # Название команды: есть буквы, нет только цифр/символов
                if re.search(r"[А-ЯёA-Z][а-яёa-z]", text) and len(text) > 2:
                    name_cell = cell
                    break

            if name_cell is None:
                continue

            team_name_ru = name_cell.get_text(strip=True)
            # Убираем лишнее (рейтинг, значки)
            team_name_ru = re.sub(r"^\d+\.", "", team_name_ru).strip()
            team_name_en = to_en(team_name_ru)

            # Числовые ячейки после ячейки с именем
            num_cells = []
            found_name = False
            for cell in cells:
                if cell == name_cell:
                    found_name = True
                    continue
                if found_name:
                    num_cells.append(cell.get_text(strip=True))

            # Ожидаемый порядок: И В Н П Г О  (или похожий)
            # Пробуем определить позиции по паттернам
            w = d = l = gf = ga = pts = played = 0

            if len(num_cells) >= 6:
                played = safe_int(num_cells[0])
                w      = safe_int(num_cells[1])
                d      = safe_int(num_cells[2])
                l      = safe_int(num_cells[3])
                # Голы могут быть "3:1" или два отдельных числа
                goals_text = num_cells[4]
                if ":" in goals_text or "-" in goals_text:
                    gf, ga = parse_goals(goals_text)
                else:
                    gf = safe_int(goals_text)
                    ga = safe_int(num_cells[5]) if len(num_cells) > 5 else 0
                pts = safe_int(num_cells[-1])
            elif len(num_cells) >= 4:
                played = safe_int(num_cells[0])
                pts    = safe_int(num_cells[-1])

            teams.append({
                "name":   team_name_en,
                "w":      w,
                "d":      d,
                "l":      l,
                "gf":     gf,
                "ga":     ga,
                "points": pts,
            })

        if len(teams) >= 2:
            groups[letter] = {"teams": teams}

    return groups


def load_current(path: Path) -> dict:
    """Загружает текущий tournament.json."""
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_output(current: dict, new_groups: dict) -> dict:
    """
    Объединяет старые данные с новыми:
    - группы заменяются свежими данными
    - tournament_winner сохраняется если уже выставлен
    """
    return {
        "_comment": (
            "Автоматически обновляется GitHub Actions каждые 30 минут. "
            "tournament_winner — установите вручную после финала."
        ),
        "tournament_winner": current.get("tournament_winner", None),
        "groups": new_groups if new_groups else current.get("groups", {}),
    }


def main():
    repo_root = Path(__file__).parent.parent
    out_path = repo_root / "tournament.json"

    print(f"Загружаю данные с {URL} …")
    try:
        html = fetch_html()
    except Exception as e:
        print(f"ОШИБКА загрузки страницы: {e}", file=sys.stderr)
        sys.exit(1)

    print("Парсю таблицы групп …")
    new_groups = parse_groups(html)

    if not new_groups:
        print("ОШИБКА: группы не найдены — структура страницы могла измениться.",
              file=sys.stderr)
        sys.exit(1)

    print(f"Найдено групп: {sorted(new_groups.keys())}")
    for letter, grp in sorted(new_groups.items()):
        names = [t["name"] for t in grp["teams"]]
        print(f"  Группа {letter}: {', '.join(names)}")

    current = load_current(out_path)
    output = build_output(current, new_groups)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"tournament.json обновлён → {out_path}")


if __name__ == "__main__":
    main()
