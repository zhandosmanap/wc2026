"""
Парсер турнирных таблиц ЧМ 2026 с championat.com.

Структура страницы (выяснена из реального HTML):
  - Группы A–L в блоках data-type="group"
  - Заголовок группы: <div class="tournament-title _hidden-td">Группа A</div>
  - Таблица: <table class="results-table table table-stripe ...">
  - Строки команд: <tr> в <tbody>
  - Имя команды: <span class="table-item__name">
  - Колонки (TD 6–12): И  В  Н  П  Мячи  О  %
    TD6=И  TD7=В  TD8=Н  TD9=П  TD10=Мячи("0-0")  TD11=О  TD12=%
"""

import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://www.championat.com/football/_worldcup/tournament/6858/table/"

# Перевод с русского на английский (для совпадения с bets.json и index.html)
NAME_MAP = {
    "Испания": "Spain", "Франция": "France", "Аргентина": "Argentina",
    "Португалия": "Portugal", "Швейцария": "Switzerland", "Англия": "England",
    "Бразилия": "Brazil", "Нидерланды": "Netherlands", "США": "USA",
    "Мексика": "Mexico", "Канада": "Canada", "Германия": "Germany",
    "Бельгия": "Belgium", "Хорватия": "Croatia", "Япония": "Japan",
    "Сенегал": "Senegal", "Марокко": "Morocco", "Сербия": "Serbia",
    "Польша": "Poland", "Дания": "Denmark", "Уругвай": "Uruguay",
    "Колумбия": "Colombia", "Чили": "Chile", "Перу": "Peru",
    "Эквадор": "Ecuador", "Венесуэла": "Venezuela", "Боливия": "Bolivia",
    "Панама": "Panama", "Коста-Рика": "Costa Rica", "Ямайка": "Jamaica",
    "Гондурас": "Honduras", "Гватемала": "Guatemala", "Гаити": "Haiti",
    "Южная Корея": "South Korea", "Австралия": "Australia",
    "Новая Зеландия": "New Zealand", "Саудовская Аравия": "Saudi Arabia",
    "Иран": "Iran", "Турция": "Turkey", "Украина": "Ukraine",
    "Чехия": "Czech Republic", "Южная Африка": "South Africa", "ЮАР": "South Africa",
    "Камерун": "Cameroon", "Кот-д'Ивуар": "Ivory Coast",
    "ДР Конго": "DR Congo", "Кения": "Kenya", "Филиппины": "Philippines",
    "Катар": "Qatar", "Босния и Герцеговина": "Bosnia and Herzegovina",
    "Албания": "Albania", "Словения": "Slovenia", "Словакия": "Slovakia",
    "Румыния": "Romania", "Венгрия": "Hungary", "Греция": "Greece",
    "Австрия": "Austria", "Тунис": "Tunisia", "Нигерия": "Nigeria",
    "Гана": "Ghana", "Египет": "Egypt", "Алжир": "Algeria",
    "Индонезия": "Indonesia", "Узбекистан": "Uzbekistan",
    "Ирак": "Iraq", "Иордания": "Jordan", "Парагвай": "Paraguay",
    "Куба": "Cuba", "Конго": "DR Congo",
    "Шотландия": "Scotland", "Швеция": "Sweden", "Норвегия": "Norway",
    "Кюрасао": "Curacao", "Кабо-Верде": "Cape Verde",
    "Алжир": "Algeria", "Египет": "Egypt", "Гана": "Ghana",
    "Катар": "Qatar", "Германия": "Germany", "Австрия": "Austria",
    "Босния и Герцеговина": "Bosnia and Herzegovina",
}


def to_en(name: str) -> str:
    name = name.strip()
    return NAME_MAP.get(name, name)


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def safe_int(text: str) -> int:
    try:
        return int(re.sub(r"[^\d]", "", text.strip()) or "0")
    except ValueError:
        return 0


def parse_goals(text: str):
    """'3-1' или '3:1' → (3, 1)"""
    m = re.search(r"(\d+)\D+(\d+)", text.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def fetch_html() -> str:
    req = Request(URL, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8")


def parse_groups(html: str) -> dict:
    groups = {}

    # Каждая группа начинается с:
    #   <div class="results-table__title tournament-title _hidden-dt">Группа A</div>
    # Разбиваем HTML на блоки по этому маркеру
    parts = re.split(r'(?=results-table__title tournament-title _hidden-dt)', html)

    for block in parts:
        # Определяем букву группы
        m = re.search(r"Групп[аa]\s+([A-L])", block)
        if not m:
            continue
        letter = m.group(1).upper()

        # Находим <tbody> в блоке
        tbody_m = re.search(r"<tbody>(.*?)</tbody>", block, re.S)
        if not tbody_m:
            continue

        tbody = tbody_m.group(1)
        teams = []

        # Каждая строка <tr> = одна команда
        rows = re.findall(r"<tr>(.*?)</tr>", tbody, re.S)
        for row in rows:
            # Все ячейки <td>
            tds_raw = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(tds_raw) < 11:
                continue

            # TD 1: имя команды из <span class="table-item__name">
            name_m = re.search(r'table-item__name">([^<]+)<', tds_raw[1])
            if not name_m:
                continue
            name_ru = name_m.group(1).strip()

            # TD 6=И  TD 7=В  TD 8=Н  TD 9=П  TD 10=Мячи  TD 11=О
            played = safe_int(strip_tags(tds_raw[6]))
            wins   = safe_int(strip_tags(tds_raw[7]))
            draws  = safe_int(strip_tags(tds_raw[8]))
            losses = safe_int(strip_tags(tds_raw[9]))
            goals_str = strip_tags(tds_raw[10]).strip()
            gf, ga = parse_goals(goals_str)
            points = safe_int(strip_tags(tds_raw[11]))

            teams.append({
                "name":   to_en(name_ru),
                "w":      wins,
                "d":      draws,
                "l":      losses,
                "gf":     gf,
                "ga":     ga,
                "points": points,
            })

        if len(teams) >= 2:
            groups[letter] = {"teams": teams}

    return groups


def main():
    repo_root = Path(__file__).parent.parent
    out_path = repo_root / "tournament.json"

    print(f"Загружаю {URL} ...")
    try:
        html = fetch_html()
    except Exception as e:
        print(f"ОШИБКА загрузки: {e}", file=sys.stderr)
        sys.exit(1)

    print("Парсю таблицы ...")
    groups = parse_groups(html)

    if not groups:
        print("ОШИБКА: группы не найдены.", file=sys.stderr)
        sys.exit(1)

    print(f"Найдено групп: {sorted(groups.keys())}")
    for letter in sorted(groups.keys()):
        names = [t["name"] for t in groups[letter]["teams"]]
        pts   = [t["points"] for t in groups[letter]["teams"]]
        print(f"  Группа {letter}: {', '.join(f'{n}({p})' for n, p in zip(names, pts))}")

    # Сохраняем tournament_winner из текущего файла
    current = {}
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            current = json.load(f)

    output = {
        "_comment": (
            "Обновляется автоматически GitHub Actions каждые 30 минут. "
            "tournament_winner — установите вручную после финала (название команды на английском)."
        ),
        "tournament_winner": current.get("tournament_winner", None),
        "groups": groups,
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Готово: {out_path}")


if __name__ == "__main__":
    main()
