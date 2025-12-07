import chess
from utils import PIECE_VALUES

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_defended_squares(board, square):
    """Возвращает множество полей, которые защищает фигура на square."""
    # Трюк: ставим на это поле вражескую фигуру и смотрим, бьем ли мы её.
    # Но проще использовать attacks() + рентген, но attacks() показывает, куда фигура может ПОЙТИ.
    # В python-chess .attacks() возвращает битовые маски полей под боем.
    # Для защиты своих фигур логика сложнее, но упрощенно attacks() работает и для защиты.
    return board.attacks(square)

def material_balance(board):
    """Считает простой материальный баланс (Белые - Черные)."""
    score = 0
    for sq, piece in board.piece_map().items():
        val = PIECE_VALUES.get(piece.piece_type, 0)
        if piece.color == chess.WHITE:
            score += val
        else:
            score -= val
    return score

# --- ОСНОВНЫЕ КЛАССИФИКАТОРЫ ---

def is_trapped_piece(board, move):
    """
    МОТИВ: Ловля фигуры (Trapped Piece).
    Логика: После нашего хода у вражеской фигуры (ценнее пешки)
    не остается безопасных ходов, и она находится под боем.
    """
    sandbox = board.copy()
    sandbox.push(move)
    
    opponent = sandbox.turn # Теперь ход соперника
    my_color = not opponent
    
    # Проходим по всем фигурам соперника
    for sq, piece in sandbox.piece_map().items():
        if piece.color == opponent and piece.piece_type != chess.PAWN and piece.piece_type != chess.KING:
            # 1. Фигура должна быть под боем
            if not sandbox.is_attacked_by(my_color, sq):
                continue
                
            # 2. У фигуры не должно быть безопасных ходов (включая взятия)
            # Генерируем псевдо-легальные ходы только для этой фигуры
            has_safe_escape = False
            # Получаем все ходы этой фигуры
            # В python-chess нет простого способа получить ходы конкретной фигуры без перебора legal_moves,
            # но можно перебрать legal_moves и фильтровать по from_square
            
            for m in sandbox.legal_moves:
                if m.from_square == sq:
                    # Проверяем, безопасно ли поле назначения
                    # (Для простоты: если поле не бьется нами. 
                    # Глубокий анализ требует рекурсии, но статика сработает для 90% случаев)
                    
                    # Нюанс: is_attacked_by не учитывает, что мы могли съесть атакующего.
                    # Поэтому делаем ход в песочнице 2-го уровня
                    sandbox2 = sandbox.copy()
                    sandbox2.push(m)
                    
                    # Если после хода фигуру не съедят сразу
                    if not sandbox2.is_attacked_by(my_color, m.to_square):
                        has_safe_escape = True
                        break
            
            if not has_safe_escape:
                return True
    return False

def is_sacrifice(board, move):
    """
    МОТИВ: Жертва (Sacrifice).
    Логика: Мы добровольно ставим фигуру под бой или отдаем материал, 
    но так как move - это Best Move (лучший), значит это оправданная жертва.
    """
    # 1. Это взятие?
    is_capture = board.is_capture(move)
    
    piece = board.piece_at(move.from_square)
    if not piece: return False # На всякий случай
    
    # Ценность нашей фигуры
    my_val = PIECE_VALUES.get(piece.piece_type, 0)
    
    sandbox = board.copy()
    sandbox.push(move)
    
    sq = move.to_square
    opponent = sandbox.turn
    
    # Бьют ли нас на новом поле?
    attackers = sandbox.attackers(opponent, sq)
    if not attackers:
        return False # Никто не бьет - не жертва
        
    # Найдем минимальную ценность атакующего
    min_attacker_val = 100
    for atk_sq in attackers:
        atk_p = sandbox.piece_at(atk_sq)
        if atk_p:
            val = PIECE_VALUES.get(atk_p.piece_type, 0)
            if val < min_attacker_val:
                min_attacker_val = val
                
    # --- КРИТЕРИИ ЖЕРТВЫ ---
    
    # А. Мы пошли под бой пешки (или более дешевой фигуры), и наша фигура дорогая
    if min_attacker_val < my_val:
        return True
        
    # Б. Мы съели защищенную фигуру, которая ДЕШЕВЛЕ нашей (обмен ферзя на коня и т.д.)
    # move was capture. Target was lower value. Target was defended (we checked attackers above).
    if is_capture:
        # Восстановим кого съели
        victim = board.piece_at(sq)
        if victim:
            victim_val = PIECE_VALUES.get(victim.piece_type, 0)
            # Если мы отдали Ферзя(9) за Коня(3), и нас могут забрать
            if my_val > victim_val and attackers:
                return True

    return False

def is_removing_the_defender(board, move):
    """
    МОТИВ: Уничтожение защитника (Removing the Defender).
    Логика: Мы съели фигуру. Эта фигура защищала кого-то еще. 
    Теперь этот "кто-то" стал беззащитным (hanging) или мы можем поставить мат.
    """
    if not board.is_capture(move): return False
    
    victim_sq = move.to_square
    victim = board.piece_at(victim_sq)
    if not victim: return False # Взятие на проходе обрабатывается отдельно, но здесь пропустим для простоты
    
    # 1. Что защищала эта фигура?
    # Чтобы узнать это, посмотрим attacks() жертвы ДО хода
    victim_attacks = board.attacks(victim_sq)
    
    sandbox_after = board.copy()
    sandbox_after.push(move) # Сделали ход (съели защитника)
    
    my_color = not sandbox_after.turn
    op_color = sandbox_after.turn
    
    for defended_sq in victim_attacks:
        piece_defended = board.piece_at(defended_sq)
        
        # Нас интересуют только союзники жертвы
        if piece_defended and piece_defended.color == victim.color:
            
            # 2. Стала ли эта фигура уязвимой ПОСЛЕ взятия?
            
            # Бьем ли мы её теперь?
            is_attacked_now = sandbox_after.is_attacked_by(my_color, defended_sq)
            
            # Защищена ли она кем-то ЕЩЕ?
            is_defended_now = sandbox_after.is_attacked_by(op_color, defended_sq)
            
            if is_attacked_now and not is_defended_now:
                return True
                
            # Доп. критерий: Если это был Мат, и защитник мешал (сложно проверить быстро)
            # Но можно проверить: Если фигура была ценной и теперь висит
            val = PIECE_VALUES.get(piece_defended.piece_type, 0)
            if is_attacked_now and val >= 3: # Если под боем остался кто-то ценный
                 return True

    return False

def is_missed_hanging_piece(board, best_move):
    if not board.is_capture(best_move): return False
    if board.is_en_passant(best_move): return False
    to_square = best_move.to_square
    victim_color = not board.turn
    return not board.is_attacked_by(victim_color, to_square)

def is_moving_into_danger(board, move):
    sandbox = board.copy()
    sandbox.push(move)
    my_square = move.to_square
    attacker_color = sandbox.turn
    my_color = not sandbox.turn
    if not sandbox.attackers(attacker_color, my_square): return False
    if sandbox.attackers(my_color, my_square): return False
    return True

def is_fork(board, move):
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
    sandbox = board.copy()
    sandbox.push(move)
    op_color = sandbox.turn
    my_attacks = sandbox.attacks(move.to_square)
    for sq in my_attacks:
        target = sandbox.piece_at(sq)
        if target and target.color == op_color:
            if sandbox.pin(op_color, sq) != chess.BB_ALL: return True
    attackers = sandbox.attackers(op_color, move.to_square)
    for sq in attackers:
        pin_mask = sandbox.pin(op_color, sq)
        if pin_mask != chess.BB_ALL:
            if not (pin_mask & chess.BB_SQUARES[move.to_square]): return True
    return False

def is_double_check(board, move):
    sandbox = board.copy()
    sandbox.push(move)
    return len(sandbox.checkers()) > 1

def is_discovered_check(board, move):
    sandbox = board.copy()
    sandbox.push(move)
    checkers = sandbox.checkers()
    if not checkers: return False 
    if move.to_square not in checkers: return True
    if len(checkers) > 1: return True
    return False

def is_discovered_attack(board, move):
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
                between_mask = chess.between(atk_sq, sq)
                if (between_mask & (1 << from_sq)): 
                    return True
    return False