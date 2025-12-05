import chess
from utils import PIECE_VALUES

def is_missed_hanging_piece(board, best_move):
    """Не забрал бесплатную фигуру."""
    if not board.is_capture(best_move): return False
    if board.is_en_passant(best_move): return False
    to_square = best_move.to_square
    victim_color = not board.turn
    return not board.is_attacked_by(victim_color, to_square)

def is_moving_into_danger(board, move):
    """Пошел под бой (зевнул фигуру)."""
    sandbox = board.copy()
    sandbox.push(move)
    my_square = move.to_square
    attacker_color = sandbox.turn
    my_color = not sandbox.turn
    
    # Если не бьют - ок
    if not sandbox.attackers(attacker_color, my_square): return False
    # Если бьют, но защищено - ок (размен)
    if sandbox.attackers(my_color, my_square): return False
    return True

def is_fork(board, move):
    """Вилка: нападение на 2+ цели."""
    sandbox = board.copy()
    sandbox.push(move)
    attacker_sq = move.to_square
    attacker_type = sandbox.piece_type_at(attacker_sq)
    
    if attacker_type == chess.KING: return False
    
    targets = 0
    opponent_color = sandbox.turn
    attacks = sandbox.attacks(attacker_sq)
    
    for sq in attacks:
        piece = sandbox.piece_at(sq)
        if piece and piece.color == opponent_color:
            if piece.piece_type == chess.PAWN: continue
            
            is_valuable = PIECE_VALUES.get(piece.piece_type, 0) > PIECE_VALUES.get(attacker_type, 0)
            is_hanging = not sandbox.is_attacked_by(opponent_color, sq)
            
            if is_valuable or is_hanging or piece.piece_type == chess.KING:
                targets += 1
    return targets >= 2

def is_skewer(board, move):
    """Линейный удар (Рентген)."""
    attacker_sq = move.to_square
    sandbox = board.copy()
    sandbox.push(move)
    attacker_type = sandbox.piece_type_at(attacker_sq)
    
    if attacker_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]: return False
    
    opponent_color = sandbox.turn
    direct_attacks = sandbox.attacks(attacker_sq)
    
    for front_sq in direct_attacks:
        front_piece = sandbox.piece_at(front_sq)
        if front_piece and front_piece.color == opponent_color:
            temp = sandbox.remove_piece_at(front_sq)
            xray_attacks = sandbox.attacks(attacker_sq)
            skewer_found = False
            
            for back_sq in xray_attacks:
                back_piece = sandbox.piece_at(back_sq)
                if back_piece and back_piece.color == opponent_color:
                    val_front = PIECE_VALUES.get(front_piece.piece_type, 0)
                    val_back = PIECE_VALUES.get(back_piece.piece_type, 0)
                    
                    if val_front > val_back or front_piece.piece_type == chess.KING:
                        skewer_found = True
            
            sandbox.set_piece_at(front_sq, temp)
            if skewer_found: return True
    return False

def is_pin(board, move):
    """Связка (Pin)."""
    sandbox = board.copy()
    sandbox.push(move)
    op_color = sandbox.turn
    
    # 1. Напали на связанного
    my_attacks = sandbox.attacks(move.to_square)
    for sq in my_attacks:
        target = sandbox.piece_at(sq)
        if target and target.color == op_color:
            if sandbox.pin(op_color, sq) != chess.BB_ALL: return True
            
    # 2. Сами под защитой связки
    attackers = sandbox.attackers(op_color, move.to_square)
    for sq in attackers:
        pin_mask = sandbox.pin(op_color, sq)
        if pin_mask != chess.BB_ALL:
            if not (pin_mask & chess.BB_SQUARES[move.to_square]): return True
    return False

def is_double_check(board, move):
    """Двойной шах."""
    sandbox = board.copy()
    sandbox.push(move)
    return len(sandbox.checkers()) > 1

def is_discovered_check(board, move):
    """Вскрытый шах."""
    sandbox = board.copy()
    sandbox.push(move)
    checkers = sandbox.checkers()
    
    if not checkers: return False 
    if move.to_square not in checkers: return True
    if len(checkers) > 1: return True
    return False

def is_discovered_attack(board, move):
    """Вскрытое нападение."""
    from_sq = move.from_square
    sandbox = board.copy()
    sandbox.push(move)
    my_color = not sandbox.turn 
    op_color = sandbox.turn     
    
    for sq, piece in sandbox.piece_map().items():
        if piece.color == op_color:
            if piece.piece_type in [chess.KING, chess.PAWN]: continue
            
            attackers = sandbox.attackers(my_color, sq)
            for atk_sq in attackers:
                if atk_sq == move.to_square: continue
                
                atk_piece = sandbox.piece_at(atk_sq)
                if atk_piece.piece_type not in [chess.BISHOP, chess.ROOK, chess.QUEEN]: continue
                
                # Геометрия: from_sq должен лежать между атакующим и целью
                between_mask = chess.between(atk_sq, sq)
                if (between_mask & (1 << from_sq)): 
                    return True
    return False