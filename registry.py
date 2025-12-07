import tactics
import middlegame

# ОШИБКИ ИГРОКА (Blunders) - Проверяем, когда оценка упала
BLUNDER_CHECKS = [
    (tactics.is_moving_into_danger, "Подставил фигуру"),
]

# ТАКТИКА (Tactics) - Проверяем, когда оценка упала (упущенные возможности)
TACTICAL_CHECKS = [
    (tactics.is_fork, "Вилка"),
    (tactics.is_pin, "Связка"),
    (tactics.is_skewer, "Линейный удар"),
    (tactics.is_double_check, "Двойной шах"),
    (tactics.is_discovered_check, "Вскрытый шах"),
    (tactics.is_discovered_attack, "Вскрытое нападение"),
    (tactics.is_missed_hanging_piece, "Не забрал фигуру"),
    (tactics.is_sacrifice, "Жертва"),
    (tactics.is_removing_the_defender, "Уничтожение защитника"),
    (tactics.is_trapped_piece, "Ловля фигуры"),
]

# СТРАТЕГИЯ (Strategy) - Проверяем ВСЕГДА (стиль игры)
STRATEGY_CHECKS = [
    (middlegame.is_doubled_pawn_created, "Сдвоил пешки"),
    (middlegame.is_isolated_pawn_created, "Изолировал пешку"),
    (middlegame.missed_open_file, "Не занял открытую линию"),
]

def get_strategy_tags(board, move, best_move):
    """
    Проверяет стратегические особенности хода.
    Вызывается на КАЖДОМ ходу ученика.
    """
    tags = []
    board_after = board.copy()
    board_after.push(move)

    for func, label in STRATEGY_CHECKS:
        if func == middlegame.missed_open_file:
             # Особая сигнатура для открытых линий
             if func(board, best_move, move): tags.append(label)
        else:
             # Стандартная сигнатура (до, после, ход)
             if func(board_before=board, board_after=board_after, move=move): tags.append(label)
    return tags

def get_tactical_tags(board, move, best_move):
    """
    Проверяет тактические зевки и упущенные возможности.
    Вызывается ТОЛЬКО если оценка упала (ошибка).
    """
    tags = []

    # 1. Ошибки игрока (Blunders)
    for func, label in BLUNDER_CHECKS:
        if func(board, move): tags.append(label)

    # 2. Тактика (на лучшем ходе - что упустил)
    for func, label in TACTICAL_CHECKS:
        if func(board, best_move): tags.append(label)

    return tags