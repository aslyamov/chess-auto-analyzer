import tactics
import middlegame

# ОШИБКИ ИГРОКА (Blunders)
# (Функция проверки хода игрока, Текст ошибки)
BLUNDER_CHECKS = [
    (tactics.is_moving_into_danger, "Подставил фигуру"),
]

# ТАКТИКА (Tactics) - что упустил игрок (проверяем лучший ход)
# (Функция проверки лучшего хода, Текст)
TACTICAL_CHECKS = [
    (tactics.is_fork, "Вилка"),
    (tactics.is_pin, "Связка"),
    (tactics.is_skewer, "Линейный удар"),
    (tactics.is_double_check, "Двойной шах"),
    (tactics.is_discovered_check, "Вскрытый шах"),
    (tactics.is_discovered_attack, "Вскрытое нападение"),
    (tactics.is_missed_hanging_piece, "Не забрал фигуру"),
]

# СТРАТЕГИЯ (Strategy) - сравниваем До и После
STRATEGY_CHECKS = [
    (middlegame.is_doubled_pawn_created, "Сдвоил пешки"),
    (middlegame.is_isolated_pawn_created, "Изолировал пешку"),
    (middlegame.missed_open_file, "Не занял открытую линию"),
]

def get_all_tags(board, move, best_move):
    """Прогоняет все проверки и возвращает список тегов."""
    tags = []

    # 1. Ошибки игрока
    for func, label in BLUNDER_CHECKS:
        if func(board, move): tags.append(label)

    # 2. Тактика (на лучшем ходе)
    for func, label in TACTICAL_CHECKS:
        if func(board, best_move): tags.append(label)

    # 3. Стратегия
    board_after = board.copy()
    board_after.push(move)

    for func, label in STRATEGY_CHECKS:
        if func == middlegame.missed_open_file:
             # Для открытых линий сигнатура отличается
             if func(board, best_move, move): tags.append(label)
        else:
             # ИСПРАВЛЕНИЕ: Убрали лишний "board" в начале
             if func(board_before=board, board_after=board_after, move=move): tags.append(label)

    return tags