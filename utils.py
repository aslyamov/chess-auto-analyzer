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
    """Считает разницу оценки (потерю) между лучшим ходом и ходом игрока."""
    engine_cp = engine_score.score(mate_score=mate_value)
    move_cp = move_score.score(mate_score=mate_value)
    
    if engine_cp is None or move_cp is None:
        return 0
        
    if turn == chess.WHITE:
        diff = engine_cp - move_cp
    else:
        diff = move_cp - engine_cp
        
    return max(0, diff)

def get_mate_comment(mate_turns):
    """Форматирует текст 'Мат в X ходов'."""
    if mate_turns == 1: suffix = "ход"
    elif 2 <= mate_turns <= 4: suffix = "хода"
    else: suffix = "ходов"
    return f"Мат в {mate_turns} {suffix}"