import chess
from chess import pgn

# Ценность фигур
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100
}

# Названия полей (a1..h8) для красивого вывода
SQUARE_NAMES = [chess.SQUARE_NAMES[i] for i in range(64)]

def get_error_type(cp_loss, config):
    """Определяет тип ошибки (зевок, ошибка, неточность) по потере пешек."""
    thresholds = config["thresholds"]
    if cp_loss >= thresholds["blunder"]:
        return chess.pgn.NAG_BLUNDER
    elif cp_loss >= thresholds["mistake"]:
        return chess.pgn.NAG_MISTAKE
    elif cp_loss >= thresholds["inaccuracy"]:
        return chess.pgn.NAG_DUBIOUS_MOVE
    return None

def calculate_score_difference(engine_score, move_score, turn, mate_value):
    """
    Считает разницу оценки (потерю) с использованием PovScore.
    engine_score и move_score — это объекты PovScore из python-chess.
    """
    # 1. Приводим обе оценки к точке зрения игрока, который делал ход (turn)
    # Если turn=Black, а оценка -5.0 (значит выигрывают черные), 
    # то pov(Black) вернет +5.0 (хорошо для игрока).
    
    best_val = engine_score.pov(turn).score(mate_score=mate_value)
    actual_val = move_score.pov(turn).score(mate_score=mate_value)
    
    if best_val is None or actual_val is None:
        return 0
    
    # 2. Теперь математика всегда одинаковая: Лучшее - Реальное
    diff = best_val - actual_val
    
    # Округляем отрицательные значения (иногда движок на малых глубинах 
    # может оценить ход человека чуть выше своего "лучшего", это шум)
    return max(0, diff)

def get_mate_comment(mate_turns):
    """Форматирует текст 'Мат в X ходов'."""
    if mate_turns == 1: suffix = "ход"
    elif 2 <= mate_turns <= 4: suffix = "хода"
    else: suffix = "ходов"
    return f"Мат в {mate_turns} {suffix}"