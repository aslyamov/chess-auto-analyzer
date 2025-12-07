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

# Настройка логгера будет происходить после загрузки конфига
def setup_logging(output_folder):
    log_file = os.path.join(output_folder, "chess_log.txt")
    
    # Сбрасываем старые хендлеры, если были
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def load_config(path="config.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[CRITICAL] Не удалось загрузить конфиг: {e}")
        sys.exit(1)

def get_pgn_files(input_folder):
    files = []
    if not os.path.exists(input_folder):
        logging.warning(f"Папка '{input_folder}' не найдена. Создаю новую.")
        try:
            os.makedirs(input_folder)
        except Exception as e:
            logging.error(f"Не удалось создать папку {input_folder}: {e}")
        return []

    for f in os.listdir(input_folder):
        if f.endswith(".pgn"):
            files.append(os.path.join(input_folder, f))
    return files

def normalize_name(name):
    return name.strip().lower() if name else "unknown"

def find_all_students(pgn_files, config):
    threshold = config.get("student_game_count_trigger", 6)
    forced_list = config.get("forced_students", [])
    forced_set = {normalize_name(x) for x in forced_list}
    
    logging.info("Поиск учеников...")
    
    if threshold == 0:
        if not forced_set:
            logging.error("Trigger=0 и forced_students пуст.")
            return {}
        target_filter = forced_set
    else:
        target_filter = None 

    player_counts = Counter()
    
    for path in pgn_files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                while True:
                    h = chess.pgn.read_headers(f)
                    if h is None: break
                    w = normalize_name(h.get("White", "?"))
                    b = normalize_name(h.get("Black", "?"))
                    
                    if target_filter:
                        if w in target_filter: player_counts[w] += 1
                        if b in target_filter: player_counts[b] += 1
                    else:
                        player_counts[w] += 1
                        player_counts[b] += 1
        except: continue

    final_students = {}
    if threshold > 0:
        for name, count in player_counts.items():
            if count > threshold or name in forced_set:
                final_students[name] = count
    else:
        final_students = dict(player_counts)

    logging.info(f"Найдено учеников: {len(final_students)}")
    for name, cnt in final_students.items():
        logging.info(f" [+] {name}: {cnt} партий")
        
    return final_students

def generate_reports(global_stats, output_folder):
    logging.info(f"Создание отчетов в папке {output_folder}...")
    for name, data in global_stats.items():
        safe = "".join([c for c in name if c.isalnum() or c in ' _-']).strip()
        filename = f"Report_{safe}.txt"
        full_path = os.path.join(output_folder, filename)
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(f"ОТЧЕТ: {name}\n{'='*30}\n\n")
            
            f.write(f"1. ДЕБЮТ (Партий: {data['games']}):\n")
            if not data["op_errors"]: f.write("- Нет грубых ошибок.\n")
            for k, v in data["op_errors"].items(): f.write(f"- {k}: {v}\n")
            
            f.write(f"\n2. ТАКТИКА (Ошибки, влияющие на оценку):\n")
            total_tac = sum(data["tac_errors"].values())
            f.write(f"   Всего ошибок: {total_tac}\n")
            for k, v in sorted(data["tac_errors"].items()): f.write(f"- {k}: {v}\n")

            f.write(f"\n3. СТРАТЕГИЯ (Стиль игры / Постоянные паттерны):\n")
            for k, v in sorted(data["strat_stats"].items()): f.write(f"- {k}: {v}\n")
            
            f.write(f"\n4. ТЕХНИКА (Не выиграно с перевесом +10): {data['tech_errors']}\n")

def process_game(game, engine, config, students_data, global_stats, tracking_info):
    board = game.board()
    node = game
    
    w_raw = game.headers.get('White', '?')
    b_raw = game.headers.get('Black', '?')
    result = game.headers.get('Result', '*')
    
    w_norm = normalize_name(w_raw)
    b_norm = normalize_name(b_raw)
    
    an_white = w_norm in students_data
    an_black = b_norm in students_data
    
    if not an_white and not an_black: return False
    
    # --- ЛОГИРОВАНИЕ ---
    tracking_info['global_game_counter'] += 1
    gg_num = tracking_info['global_game_counter']

    active_students = []
    if an_white: active_students.append((w_raw, w_norm))
    if an_black: active_students.append((b_raw, b_norm))

    log_parts = []
    for raw_name, norm_name in active_students:
        s_idx = tracking_info['student_indices'].get(norm_name, '?')
        s_total = tracking_info['total_students']
        tracking_info['student_progress'][norm_name] += 1
        p_curr = tracking_info['student_progress'][norm_name]
        p_total = students_data.get(norm_name, '?')
        log_parts.append(f"[Ученик {s_idx}/{s_total}] {raw_name} ({p_curr}/{p_total})")

    logging.info(f"Партия {gg_num}. {' | '.join(log_parts)}")
    
    # --- ИНИЦИАЛИЗАЦИЯ ---
    for raw_name, norm_name in active_students:
        if raw_name not in global_stats:
            global_stats[raw_name] = {
                "games": 0, "op_errors": Counter(), "tac_errors": Counter(), 
                "strat_stats": Counter(), "tech_errors": 0
            }
        global_stats[raw_name]["games"] += 1

    op_trackers = {}
    if an_white: op_trackers[chess.WHITE] = {"center_control": False, "has_castled": False, "moved_pieces": set(), "target_center": [chess.E4, chess.D4], "checked": False}
    if an_black: op_trackers[chess.BLACK] = {"center_control": False, "has_castled": False, "moved_pieces": set(), "target_center": [chess.E5, chess.D5], "checked": False}

    tech_advantage_flag = {chess.WHITE: False, chess.BLACK: False}

    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        turn = board.turn
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
            if turn in op_trackers and not op_trackers[turn]["checked"] and board.fullmove_number == 15:
                rep = opening.check_opening_principles(op_trackers[turn], turn)
                if rep:
                    msg = f"; {rep}" if next_node.comment else rep
                    next_node.comment = (next_node.comment + msg) if next_node.comment else msg
                    for k in ["не захватил центр", "не сделал рокировку", "не развил фигуры"]:
                        if k in rep: global_stats[student_name]["op_errors"][k] += 1
                op_trackers[turn]["checked"] = True
            
            board.push(move); node = next_node; continue

        # --- АНАЛИЗ ---
        try:
            limit = chess.engine.Limit(depth=config["engine_depth"])
            info = engine.analyse(board, limit, multipv=1)
            if isinstance(info, list): info = info[0]
            if "pv" not in info:
                board.push(move); node = next_node; continue

            best_move = info["pv"][0]
            
            # Объект PovScore (относительная оценка)
            best_score_obj = info["score"] 

            # === 1. СТРАТЕГИЯ ===
            strat_tags = registry.get_strategy_tags(board, move, best_move)
            if strat_tags:
                for t in strat_tags:
                    global_stats[student_name]["strat_stats"][t] += 1
                strat_comment = ", ".join(strat_tags)
                if next_node.comment:
                    next_node.comment += f"; {strat_comment}"
                else:
                    next_node.comment = strat_comment

            # === 2. ТЕХНИКА ===
            if middlegame.check_technical_conversion(best_score_obj, 1000, result, turn, (turn == chess.WHITE)):
                if not tech_advantage_flag[turn]:
                    tech_advantage_flag[turn] = True
                    global_stats[student_name]["tech_errors"] += 1
                    msg = "; [Не реализовал перевес +10]" if next_node.comment else "[Не реализовал перевес +10]"
                    next_node.comment = (next_node.comment + msg) if next_node.comment else msg

            # Если ход лучший
            if move == best_move:
                # Дебют
                if turn in op_trackers and not op_trackers[turn]["checked"] and board.fullmove_number == 15:
                    rep = opening.check_opening_principles(op_trackers[turn], turn)
                    if rep:
                        msg = f"; {rep}" if next_node.comment else rep
                        next_node.comment = (next_node.comment + msg) if next_node.comment else msg
                        for k in ["не захватил центр", "не сделал рокировку", "не развил фигуры"]:
                            if k in rep: global_stats[student_name]["op_errors"][k] += 1
                    op_trackers[turn]["checked"] = True
                
                board.push(move); node = next_node; continue

            # === 3. ТАКТИКА И МАТ ===
            mate_found = False
            
            # --- УПУЩЕННЫЙ МАТ ---
            if best_score_obj.is_mate():
                # ИСПРАВЛЕНИЕ: берем .pov(turn).mate() вместо прямого .mate()
                mate_in = best_score_obj.pov(turn).mate()
                
                # Ищем мат только если он для нас положительный (мы выигрываем)
                if mate_in > 0 and mate_in <= config["mate_depth_trigger"]:
                    board.push(move); board.pop()
                    u_info = engine.analyse(board, limit, root_moves=[move])
                    u_score_obj = u_info["score"]
                    
                    # ИСПРАВЛЕНИЕ: здесь тоже .pov(turn).mate()
                    u_mate = u_score_obj.pov(turn).mate() if u_score_obj.is_mate() else 0
                    
                    if not u_score_obj.is_mate() or (u_mate > 0 and u_mate > mate_in):
                        lbl = f"Не нашел мат в {mate_in}"
                        global_stats[student_name]["tac_errors"][lbl] += 1
                        
                        next_node.nags.add(chess.pgn.NAG_BLUNDER)
                        
                        var_node = node.add_variation(best_move)
                        if "pv" in info and len(info["pv"]) > 1:
                            current_var = var_node
                            for pv_move in info["pv"][1:]:
                                current_var = current_var.add_main_variation(pv_move)
                        
                        var_node.comment = utils.get_mate_comment(mate_in)
                        mate_found = True

            # --- ОБЫЧНЫЕ ОШИБКИ ---
            if not mate_found:
                board.push(move); board.pop()
                u_info = engine.analyse(board, limit, root_moves=[move])
                u_score_obj = u_info["score"]
                
                # Передаем объекты PovScore в utils, там они корректно обрабатываются
                diff = utils.calculate_score_difference(best_score_obj, u_score_obj, turn, config["mate_score"])
                nag = utils.get_error_type(diff, config)
                
                if nag and diff >= config["error_threshold"]:
                    tags = registry.get_tactical_tags(board, move, best_move)
                    
                    if tags:
                        for t in tags: global_stats[student_name]["tac_errors"][t] += 1
                        logging.info(f"   [x] Ошибка (Ход {board.fullmove_number}): {', '.join(tags)}")
                    else:
                        global_stats[student_name]["tac_errors"]["Прочие ошибки"] += 1
                        logging.info(f"   [x] Ошибка (Ход {board.fullmove_number}): Loss {diff}")
                        
                    next_node.nags.add(nag)
                    
                    var_node = node.add_variation(best_move)
                    if "pv" in info and len(info["pv"]) > 1:
                        current_var = var_node
                        for i, pv_move in enumerate(info["pv"][1:]):
                            if i > 5: break 
                            current_var = current_var.add_main_variation(pv_move)
                    
                    all_comments = tags 
                    if all_comments: var_node.comment = ", ".join(all_comments)

        except Exception as e:
            logging.error(f"Move error: {e}")

        # Дебют (повтор логики)
        if turn in op_trackers and not op_trackers[turn]["checked"] and board.fullmove_number == 15:
            rep = opening.check_opening_principles(op_trackers[turn], turn)
            if rep:
                msg = f"; {rep}" if next_node.comment else rep
                next_node.comment = (next_node.comment + msg) if next_node.comment else msg
                for k in ["не захватил центр", "не сделал рокировку", "не развил фигуры"]:
                    if k in rep: global_stats[student_name]["op_errors"][k] += 1
            op_trackers[turn]["checked"] = True

        board.push(move)
        node = next_node
    return True

def main():
    config = load_config()
    
    input_folder = config.get("input_folder", "pgn")
    output_folder = config.get("output_folder", "pgn_analyzed")
    
    if not os.path.exists(input_folder):
        os.makedirs(input_folder, exist_ok=True)
        print(f"Создана папка для входных файлов: {input_folder}")
        
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)
        
    setup_logging(output_folder)
    
    pgn_files = get_pgn_files(input_folder)
    
    if not pgn_files:
        logging.warning(f"Файлы PGN не найдены в папке '{input_folder}'.")
        print(f"\n[!] Папка '{input_folder}' пуста. Добавьте туда файлы .pgn и запустите снова.")
        return
    
    students_data = find_all_students(pgn_files, config)
    if not students_data: return
    
    sorted_students = sorted(students_data.keys())
    student_indices = {name: i+1 for i, name in enumerate(sorted_students)}
    student_progress = {name: 0 for name in students_data}
    
    tracking_info = {
        'student_indices': student_indices,
        'student_progress': student_progress,
        'total_students': len(students_data),
        'global_game_counter': 0
    }
    
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
    
    for f in pgn_files:
        filename = os.path.basename(f)
        base = os.path.splitext(filename)[0]
        out_path = os.path.join(output_folder, f"{base}_analyze.pgn")
        
        logging.info(f"=== Файл: {filename} ===")
        
        with open(f, "r", encoding="utf-8", errors="replace") as pin, open(out_path, "w", encoding="utf-8") as pout:
            exp = chess.pgn.FileExporter(pout)
            while True:
                g = chess.pgn.read_game(pin)
                if g is None: break
                if process_game(g, engine, config, students_data, global_stats, tracking_info):
                    g.accept(exp)
                    
    engine.quit()
    generate_reports(global_stats, output_folder)
    logging.info(f"ВСЕ ГОТОВО. Результаты в папке: {output_folder}")
    print(f"\nАнализ завершен. Результаты в папке: {output_folder}")

if __name__ == "__main__":
    main()