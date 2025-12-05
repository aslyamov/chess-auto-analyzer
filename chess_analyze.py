import sys
import os
import json
import logging
import chess
import chess.pgn
import chess.engine
from collections import Counter

# Импорт наших модулей
import utils
import opening
import middlegame
import registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("chess_log.txt", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def load_config(path="config.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.critical(f"Config Error: {e}")
        sys.exit(1)

def get_pgn_files(directory="."):
    return [f for f in os.listdir(directory) if f.endswith(".pgn") and not f.endswith("_analyze.pgn")]

def normalize_name(name):
    return name.strip().lower() if name else "unknown"

def find_all_students(pgn_files, config):
    threshold = config.get("student_game_count_trigger", 6)
    forced = {normalize_name(x) for x in config.get("forced_students", [])}
    counts = Counter()
    
    logging.info("Поиск учеников...")
    for path in pgn_files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                while True:
                    h = chess.pgn.read_headers(f)
                    if h is None: break
                    counts[normalize_name(h.get("White", "?"))] += 1
                    counts[normalize_name(h.get("Black", "?"))] += 1
        except: continue
            
    students = {n for n, c in counts.items() if c > threshold}
    students.update(forced)
    
    if students: logging.info(f"Найдено учеников: {len(students)}")
    else: logging.warning("Ученики не найдены.")
    return students

def generate_reports(global_stats):
    logging.info("Создание отчетов (TXT)...")
    for name, data in global_stats.items():
        safe = "".join([c for c in name if c.isalnum() or c in ' _-']).strip()
        with open(f"Report_{safe}.txt", "w", encoding="utf-8") as f:
            f.write(f"ОТЧЕТ: {name}\n{'='*30}\n\n")
            
            f.write(f"1. ДЕБЮТ (Партий: {data['games']}):\n")
            if not data["op_errors"]: f.write("- Нет грубых ошибок.\n")
            for k, v in data["op_errors"].items(): f.write(f"- {k}: {v}\n")
            
            f.write(f"\n2. ТАКТИКА И СТРАТЕГИЯ (Всего: {sum(data['tac_errors'].values())}):\n")
            for k, v in sorted(data["tac_errors"].items()): f.write(f"- {k}: {v}\n")
            
            f.write(f"\n3. ТЕХНИКА (Не выиграно с перевесом +10): {data['tech_errors']}\n")

def process_game(game, engine, config, students, global_stats):
    board = game.board()
    node = game
    
    w_raw = game.headers.get('White', '?')
    b_raw = game.headers.get('Black', '?')
    result = game.headers.get('Result', '*')
    
    an_white = normalize_name(w_raw) in students
    an_black = normalize_name(b_raw) in students
    
    if not an_white and not an_black: return False
    
    logging.info(f"Анализ: {w_raw} vs {b_raw}")
    
    # Инициализация статистики
    for name, active in [(w_raw, an_white), (b_raw, an_black)]:
        if active:
            if name not in global_stats:
                global_stats[name] = {"games": 0, "op_errors": Counter(), "tac_errors": Counter(), "tech_errors": 0}
            global_stats[name]["games"] += 1

    # Трекеры дебюта
    op_trackers = {}
    if an_white: op_trackers[chess.WHITE] = {"center_control": False, "has_castled": False, "moved_pieces": set(), "target_center": [chess.E4, chess.D4], "checked": False}
    if an_black: op_trackers[chess.BLACK] = {"center_control": False, "has_castled": False, "moved_pieces": set(), "target_center": [chess.E5, chess.D5], "checked": False}

    # Флаг технической позиции (чтобы считать ошибку 1 раз за партию)
    tech_advantage_flag = {chess.WHITE: False, chess.BLACK: False}

    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        turn = board.turn # True=White
        student_name = w_raw if turn == chess.WHITE else b_raw
        
        # Сбор данных дебюта
        if turn in op_trackers:
            st = op_trackers[turn]
            p = board.piece_at(move.from_square)
            if p and p.piece_type == chess.PAWN and move.to_square in st["target_center"]: st["center_control"] = True
            if board.is_castling(move): st["has_castled"] = True
            st["moved_pieces"].add(move.from_square)
        
        should_analyze = (turn == chess.WHITE and an_white) or (turn == chess.BLACK and an_black)

        if not should_analyze:
            # Проверка дебюта (15 ход) на ходе соперника
            if turn in op_trackers and not op_trackers[turn]["checked"] and board.fullmove_number == 15:
                rep = opening.check_opening_principles(op_trackers[turn], turn)
                if rep:
                    msg = f" [DEBUT] {rep}"
                    if next_node.comment: next_node.comment += msg
                    else: next_node.comment = msg
                    for k in ["не захватил центр", "не сделал рокировку", "не развил фигуры"]:
                        if k in rep: global_stats[student_name]["op_errors"][k] += 1
                op_trackers[turn]["checked"] = True
            
            board.push(move); node = next_node; continue

        # --- ЗАПУСК ДВИЖКА ---
        try:
            limit = chess.engine.Limit(depth=config["engine_depth"])
            info = engine.analyse(board, limit, multipv=1)
            if isinstance(info, list): info = info[0]
            if "pv" not in info:
                board.push(move); node = next_node; continue

            best_move = info["pv"][0]
            score = info["score"].relative
            
            # 1. ТЕХНИЧЕСКАЯ ПОЗИЦИЯ
            if middlegame.check_technical_conversion(score, 1000, result, turn, (turn == chess.WHITE)):
                if not tech_advantage_flag[turn]:
                    tech_advantage_flag[turn] = True
                    global_stats[student_name]["tech_errors"] += 1
                    msg = " [Не реализовал перевес +10]"
                    if next_node.comment: next_node.comment += msg
                    else: next_node.comment = msg

            if move == best_move:
                # Проверка дебюта (даже при лучшем ходе)
                if turn in op_trackers and not op_trackers[turn]["checked"] and board.fullmove_number == 15:
                    rep = opening.check_opening_principles(op_trackers[turn], turn)
                    if rep:
                        msg = f" [DEBUT] {rep}"
                        if next_node.comment: next_node.comment += msg
                        else: next_node.comment = msg
                        for k in ["не захватил центр", "не сделал рокировку", "не развил фигуры"]:
                            if k in rep: global_stats[student_name]["op_errors"][k] += 1
                    op_trackers[turn]["checked"] = True
                
                board.push(move); node = next_node; continue

            # 2. АНАЛИЗ ОШИБОК
            mate_found = False
            # Упущенный мат
            if score.is_mate() and 0 < score.mate() <= config["mate_depth_trigger"]:
                mate_in = score.mate()
                board.push(move); board.pop()
                u_info = engine.analyse(board, limit, root_moves=[move])
                u_score = u_info["score"].relative
                u_mate = u_score.mate() if u_score.is_mate() else 0
                
                if not u_score.is_mate() or (u_mate > 0 and u_mate > mate_in):
                    lbl = f"Не нашел мат в {mate_in}"
                    global_stats[student_name]["tac_errors"][lbl] += 1
                    next_node.nags.add(chess.pgn.NAG_BLUNDER)
                    var = node.add_variation(best_move)
                    var.comment = utils.get_mate_comment(mate_in)
                    mate_found = True

            # Тактика и стратегия через REJISTRY
            if not mate_found:
                board.push(move); board.pop()
                u_info = engine.analyse(board, limit, root_moves=[move])
                u_score = u_info["score"].relative
                
                diff = utils.calculate_score_difference(score, u_score, turn, config["mate_score"])
                nag = utils.get_error_type(diff, config)
                
                if nag and diff >= config["error_threshold"]:
                    # --- ПОЛУЧАЕМ ТЕГИ ЧЕРЕЗ РЕЕСТР ---
                    tags = registry.get_all_tags(board, move, best_move)
                    
                    if tags:
                        for t in tags: global_stats[student_name]["tac_errors"][t] += 1
                    else:
                        global_stats[student_name]["tac_errors"]["Прочие ошибки"] += 1
                        
                    next_node.nags.add(nag)
                    var = node.add_variation(best_move)
                    if tags: var.comment = ", ".join(tags)

        except Exception as e:
            logging.error(f"Move error: {e}")

        # Проверка дебюта (повтор для надежности)
        if turn in op_trackers and not op_trackers[turn]["checked"] and board.fullmove_number == 15:
            rep = opening.check_opening_principles(op_trackers[turn], turn)
            if rep:
                msg = f" [DEBUT] {rep}"
                if next_node.comment: next_node.comment += msg
                else: next_node.comment = msg
                for k in ["не захватил центр", "не сделал рокировку", "не развил фигуры"]:
                    if k in rep: global_stats[student_name]["op_errors"][k] += 1
            op_trackers[turn]["checked"] = True

        board.push(move)
        node = next_node
    return True

def main():
    with open("chess_log.txt", "w", encoding="utf-8") as f: f.write("START\n")
    config = load_config()
    files = get_pgn_files()
    if not files: return
    
    students = find_all_students(files, config)
    if not students: return
    
    try:
        logging.info("Запуск движка...")
        engine = chess.engine.SimpleEngine.popen_uci(config["stockfish_path"])
        engine.configure({
            "Threads": config.get("engine_threads", 1),
            "Hash": config.get("engine_hash", 16)
        })
    except Exception as e:
        logging.critical(f"Engine fail: {e}"); return
        
    global_stats = {}
    
    for f in files:
        base = os.path.splitext(f)[0]
        out = f"{base}_analyze.pgn"
        with open(f, "r", encoding="utf-8", errors="replace") as pin, open(out, "w", encoding="utf-8") as pout:
            exp = chess.pgn.FileExporter(pout)
            while True:
                g = chess.pgn.read_game(pin)
                if g is None: break
                if process_game(g, engine, config, students, global_stats):
                    g.accept(exp)
                    
    engine.quit()
    generate_reports(global_stats)
    logging.info("DONE")

if __name__ == "__main__":
    main()