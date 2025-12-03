import chess
from chess import pgn

"""
CLASSIFIER.PY
Модуль для классификации шахматных ошибок и определения тактических мотивов.
Содержит логику проверки дебюта и алгоритмы поиска вилок, связок, вскрытых шахов и т.д.
"""

# Ценность фигур (используется для оценки угроз)
# Король = 100, чтобы он всегда считался "ценнее" любой другой фигуры.
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100
}

# Названия полей для читаемого вывода в дебютном анализе (a1..h8)
SQUARE_NAMES = [
    "a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1",
    "a2", "b2", "c2", "d2", "e2", "f2", "g2", "h2",
    "a3", "b3", "c3", "d3", "e3", "f3", "g3", "h3",
    "a4", "b4", "c4", "d4", "e4", "f4", "g4", "h4",
    "a5", "b5", "c5", "d5", "e5", "f5", "g5", "h5",
    "a6", "b6", "c6", "d6", "e6", "f6", "g6", "h6",
    "a7", "b7", "c7", "d7", "e7", "f7", "g7", "h7",
    "a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8",
]

def get_error_type(cp_loss, config):
    """
    Определяет тип ошибки (знак NAG) на основе потери пешек (cp_loss).
    Возвращает: NAG_BLUNDER (??), NAG_MISTAKE (?) или NAG_DUBIOUS_MOVE (?!)
    """
    thresholds = config["thresholds"]
    if cp_loss >= thresholds["blunder"]:
        return chess.pgn.NAG_BLUNDER, None
    elif cp_loss >= thresholds["mistake"]:
        return chess.pgn.NAG_MISTAKE, None
    elif cp_loss >= thresholds["inaccuracy"]:
        return chess.pgn.NAG_DUBIOUS_MOVE, None
    return None, None

def calculate_score_difference(engine_score, move_score, turn, mate_value):
    """
    Считает разницу в оценке (loss) между лучшим ходом и ходом игрока.
    Корректно обрабатывает оценки "Мат в X ходов".
    """
    engine_cp = engine_score.score(mate_score=mate_value)
    move_cp = move_score.score(mate_score=mate_value)
    
    if engine_cp is None or move_cp is None:
        return 0
        
    # Разница всегда должна быть положительной (потеря)
    if turn == chess.WHITE:
        diff = engine_cp - move_cp
    else:
        diff = move_cp - engine_cp
        
    return max(0, diff)

def get_mate_comment(mate_turns):
    """Генерирует текст комментария о мате с правильным склонением."""
    if mate_turns == 1: suffix = "ход"
    elif 2 <= mate_turns <= 4: suffix = "хода"
    else: suffix = "ходов"
    return f"Мат в {mate_turns} {suffix}"

# ==========================================
#          ДЕБЮТНЫЙ АНАЛИЗ
# ==========================================

def check_opening_principles(opening_stats, student_color):
    """
    Анализирует собранную статистику первых 15 ходов.
    Возвращает строку с ошибками или None, если все хорошо.
    Критерии:
    1. Был ли ход центральной пешкой (e4/d4 или e5/d5).
    2. Была ли рокировка.
    3. Развиты ли кони и слоны.
    """
    errors = []
    
    # 1. Проверка центра
    if not opening_stats["center_control"]:
        errors.append("не захватил центр пешкой")
        
    # 2. Проверка рокировки
    if not opening_stats["has_castled"]:
        errors.append("не сделал рокировку")
        
    # 3. Проверка легких фигур
    undeveloped = []
    if student_color == chess.WHITE:
        knights = {chess.B1, chess.G1}
        bishops = {chess.C1, chess.F1}
    else:
        knights = {chess.B8, chess.G8}
        bishops = {chess.C8, chess.F8}
        
    moved = opening_stats["moved_pieces"]
    
    for sq in knights:
        if sq not in moved: undeveloped.append(f"Конь ({SQUARE_NAMES[sq]})")
    for sq in bishops:
        if sq not in moved: undeveloped.append(f"Слон ({SQUARE_NAMES[sq]})")
            
    if undeveloped:
        errors.append(f"не развил фигуры: {', '.join(undeveloped)}")
        
    if not errors: return None
    
    text = "; ".join(errors)
    return f"Дебютные ошибки: {text}"

# ==========================================
#     КЛАССИФИКАТОРЫ ТАКТИЧЕСКИХ ПРИЕМОВ
# ==========================================

def is_missed_hanging_piece(board, best_move):
    """
    МОТИВ: Не забрал фигуру (Missed Hanging Piece).
    Логика: Лучший ход - это взятие фигуры, которая никем не защищена.
    """
    if not board.is_capture(best_move): return False
    if board.is_en_passant(best_move): return False
    
    to_square = best_move.to_square
    victim_color = not board.turn
    
    # Если поле жертвы не атаковано её союзниками, значит она не защищена
    return not board.is_attacked_by(victim_color, to_square)

def is_moving_into_danger(board, move):
    """
    МОТИВ: Подставил фигуру (Blunder / Hanging Piece).
    Логика: Игрок пошел на поле, которое бьется соперником, и не обеспечил защиту.
    """
    sandbox = board.copy()
    sandbox.push(move)
    
    my_square = move.to_square
    attacker_color = sandbox.turn # Ход перешел к сопернику
    my_color = not sandbox.turn
    
    # Если нас никто не бьет - все ок
    if not sandbox.attackers(attacker_color, my_square): return False
    
    # Если нас бьют, но мы защищены - это размен, а не зевок
    if sandbox.attackers(my_color, my_square): return False
    
    return True

def is_fork(board, move):
    """
    МОТИВ: Вилка (Fork).
    Логика: Фигура нападает одновременно на 2+ цели.
    Цель - это фигура, которая ценнее атакующей, либо не защищена, либо Король.
    """
    sandbox = board.copy()
    sandbox.push(move)
    
    attacker_sq = move.to_square
    attacker_type = sandbox.piece_type_at(attacker_sq)
    
    # Король вилки не ставит (обычно это не так называют)
    if attacker_type == chess.KING: return False
    
    targets = 0
    opponent_color = sandbox.turn
    attacks = sandbox.attacks(attacker_sq)
    
    for sq in attacks:
        piece = sandbox.piece_at(sq)
        if piece and piece.color == opponent_color:
            if piece.piece_type == chess.PAWN: continue
            
            # Критерии цели вилки
            is_valuable = PIECE_VALUES.get(piece.piece_type, 0) > PIECE_VALUES.get(attacker_type, 0)
            is_hanging = not sandbox.is_attacked_by(opponent_color, sq)
            is_king = (piece.piece_type == chess.KING)
            
            if is_valuable or is_hanging or is_king:
                targets += 1
                
    return targets >= 2

def is_skewer(board, move):
    """
    МОТИВ: Линейный удар / Скьер (Skewer).
    Логика: Дальнобойная фигура атакует ценную фигуру (или Короля).
    Если эту фигуру убрать, за ней обнаруживается еще одна цель.
    """
    attacker_sq = move.to_square
    sandbox = board.copy()
    sandbox.push(move)
    
    attacker_type = sandbox.piece_type_at(attacker_sq)
    # Только слон, ладья или ферзь могут делать скьер
    if attacker_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]: return False
    
    opponent_color = sandbox.turn
    direct_attacks = sandbox.attacks(attacker_sq)
    
    for front_sq in direct_attacks:
        front_piece = sandbox.piece_at(front_sq)
        if front_piece and front_piece.color == opponent_color:
            
            # Трюк: временно убираем переднюю фигуру ("Рентген")
            temp = sandbox.remove_piece_at(front_sq)
            xray_attacks = sandbox.attacks(attacker_sq)
            skewer_found = False
            
            for back_sq in xray_attacks:
                back_piece = sandbox.piece_at(back_sq)
                if back_piece and back_piece.color == opponent_color:
                    
                    val_front = PIECE_VALUES.get(front_piece.piece_type, 0)
                    val_back = PIECE_VALUES.get(back_piece.piece_type, 0)
                    
                    # Передняя фигура должна быть ценнее задней, либо это Король (Шах)
                    if val_front > val_back: skewer_found = True
                    elif front_piece.piece_type == chess.KING: skewer_found = True
            
            # Возвращаем фигуру на место
            sandbox.set_piece_at(front_sq, temp)
            
            if skewer_found: return True
    return False

def is_pin(board, move):
    """
    МОТИВ: Связка (Pin).
    Логика:
    1. Мы напали на фигуру, которая не может уйти (связана).
    2. Мы встали под бой, но нас нельзя бить, т.к. бьющая фигура связана.
    """
    sandbox = board.copy()
    sandbox.push(move)
    op_color = sandbox.turn
    
    # 1. Проверяем атаку на связанные фигуры
    my_attacks = sandbox.attacks(move.to_square)
    for sq in my_attacks:
        target = sandbox.piece_at(sq)
        if target and target.color == op_color:
            # pin возвращает маску (куда можно ходить). Если не BB_ALL - фигура связана.
            if sandbox.pin(op_color, sq) != chess.BB_ALL: return True
            
    # 2. Проверяем, защищает ли нас связка
    attackers = sandbox.attackers(op_color, move.to_square)
    for sq in attackers:
        pin_mask = sandbox.pin(op_color, sq)
        if pin_mask != chess.BB_ALL:
            # Если наше поле не лежит на линии связки, значит нас бить нельзя
            if not (pin_mask & chess.BB_SQUARES[move.to_square]): return True
    return False

def is_double_check(board, move):
    """
    МОТИВ: Двойной шах (Double Check).
    Логика: После хода короля атакуют 2 или более фигур.
    """
    sandbox = board.copy()
    sandbox.push(move)
    return len(sandbox.checkers()) > 1

def is_discovered_check(board, move):
    """
    МОТИВ: Вскрытый шах (Discovered Check).
    Логика: Шах есть, но фигура, которая только что ходила, сама на короля не нападает.
    Значит, линия открылась для дальнобойной фигуры сзади.
    """
    sandbox = board.copy()
    sandbox.push(move)
    checkers = sandbox.checkers()
    
    if not checkers: return False 
    
    # Если фигура, которой походили, сама не дает шах - значит он вскрытый
    if move.to_square not in checkers: return True
    
    # Если шахуют > 1 фигуры, значит один из шахов точно вскрытый
    if len(checkers) > 1: return True
    
    return False

def is_discovered_attack(board, move):
    """
    МОТИВ: Вскрытое нападение (Discovered Attack).
    Логика: Фигура отпрыгнула, открыв линию атаки для слона/ладьи/ферзя.
    Проверяем геометрию: старое поле фигуры лежит на линии между Агрессором и Жертвой.
    """
    from_sq = move.from_square
    sandbox = board.copy()
    sandbox.push(move)
    
    my_color = not sandbox.turn 
    op_color = sandbox.turn     
    
    for sq, piece in sandbox.piece_map().items():
        if piece.color == op_color:
            # Игнорируем Короля (это вскрытый шах) и Пешки (мелкая цель)
            if piece.piece_type == chess.KING: continue
            if piece.piece_type == chess.PAWN: continue
            
            attackers = sandbox.attackers(my_color, sq)
            for atk_sq in attackers:
                # Игнорируем прямую атаку
                if atk_sq == move.to_square: continue
                
                atk_piece = sandbox.piece_at(atk_sq)
                if atk_piece.piece_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]: continue
                
                # Проверяем, лежит ли поле, откуда мы ушли, на линии атаки
                between_mask = chess.between(atk_sq, sq)
                
                if (between_mask & (1 << from_sq)): 
                    return True
    return False