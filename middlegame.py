import chess

# === ТЕХНИЧЕСКАЯ ПОЗИЦИЯ ===
def check_technical_conversion(score, advantage_threshold, game_result, current_turn, is_white_student):
    """
    Проверяет, было ли у нас огромное преимущество (>1000cp), которое мы не реализовали (не выиграли).
    """
    # Если результат - победа ученика, ошибки нет
    if game_result == "1-0" and is_white_student: return False
    if game_result == "0-1" and not is_white_student: return False
    
    cp = score.score(mate_score=10000)
    if cp is None: return False
    
    # Если оценка >= порога (например 1000), значит у нас выиграно.
    # Но так как мы не выиграли партию (проверка выше), возвращаем True (Ошибка).
    if cp >= advantage_threshold:
        return True
    return False

# === ПЕШЕЧНЫЕ СТРУКТУРЫ ===

def get_pawns_per_file(board, color):
    """Помощник: считает пешки по вертикалям."""
    counts = [0] * 8
    pawns = board.pieces(chess.PAWN, color)
    for sq in pawns:
        file_idx = chess.square_file(sq)
        counts[file_idx] += 1
    return counts

def is_doubled_pawn_created(board_before, board_after, move):
    """Создание сдвоенных пешек."""
    piece = board_before.piece_at(move.from_square)
    if not piece or piece.piece_type != chess.PAWN:
        return False
        
    color = piece.color
    before = get_pawns_per_file(board_before, color)
    after = get_pawns_per_file(board_after, color)
    
    for f in range(8):
        if after[f] >= 2 and before[f] < 2:
            return True
    return False

def is_isolated_pawn_created(board_before, board_after, move):
    """Создание изолированной пешки."""
    color = board_before.turn 
    
    def count_iso(b_state):
        counts = get_pawns_per_file(b_state, color)
        iso = 0
        for i in range(8):
            if counts[i] > 0:
                has_l = (i > 0 and counts[i-1] > 0)
                has_r = (i < 7 and counts[i+1] > 0)
                if not has_l and not has_r: iso += counts[i]
        return iso

    return count_iso(board_after) > count_iso(board_before)

# === ОТКРЫТЫЕ ЛИНИИ ===

def missed_open_file(board, best_move, user_move):
    """Не занял открытую линию (когда комп советовал)."""
    # 1. Комп советует ладью/ферзя
    piece = board.piece_at(best_move.from_square)
    if not piece or piece.piece_type not in [chess.ROOK, chess.QUEEN]:
        return False
    
    best_file = chess.square_file(best_move.to_square)
    user_file = chess.square_file(user_move.to_square)
    
    # 2. Игрок не пошел на эту же линию
    if best_file == user_file:
        return False 
        
    # 3. Линия открыта? (нет пешек)
    for rank in range(8):
        sq = chess.square(best_file, rank)
        if board.piece_type_at(sq) == chess.PAWN:
            return False
            
    return True