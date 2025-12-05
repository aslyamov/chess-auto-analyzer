import chess
from utils import SQUARE_NAMES

def check_opening_principles(opening_stats, student_color):
    """
    Генерирует отчет по дебюту на основе статистики 15 ходов.
    Возвращает текст ошибки или None.
    """
    errors = []
    
    # 1. Центр
    if not opening_stats["center_control"]:
        errors.append("не захватил центр пешкой")
        
    # 2. Рокировка
    if not opening_stats["has_castled"]:
        errors.append("не сделал рокировку")
        
    # 3. Развитие легких фигур
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
    
    return f"Дебютные ошибки: {'; '.join(errors)}"