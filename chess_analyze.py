import sys
import os
import json
import logging
import chess
import chess.pgn
import chess.engine
from collections import Counter
import classifier

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
# Логи пишутся в файл chess_log.txt для детального разбора полетов
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("chess_log.txt", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def load_config(path="config.json"):
    """Загружает настройки (путь к движку, пороги ошибок, список учеников)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.critical(f"Не удалось загрузить конфиг: {e}", exc_info=True)
        sys.exit(1)

def get_pgn_files(directory="."):
    """Ищет все файлы .pgn в папке, игнорируя уже проанализированные (_analyze.pgn)."""
    files = []
    for filename in os.listdir(directory):
        if filename.endswith(".pgn") and not filename.endswith("_analyze.pgn"):
            files.append(filename)
    return files

def normalize_name(name):
    """Приводит имена к нижнему регистру для корректного сравнения."""
    if not name: return "unknown"
    return name.strip().lower()

def find_all_students(pgn_files, config):
    """
    Сканирует все партии, считает, сколько раз встречался каждый игрок.
    Возвращает список тех, кто сыграл больше N партий (или указан в конфиге).
    """
    threshold = config.get("student_game_count_trigger", 6)
    forced_list = config.get("forced_students", [])
    forced_list_norm = {normalize_name(x) for x in forced_list}
    
    logging.info("--- ПОИСК УЧЕНИКОВ ---")
    player_counts = Counter()
    total_games = 0
    
    for file_path in pgn_files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                while True:
                    try:
                        headers = chess.pgn.read_headers(f)
                    except ValueError: continue
                    if headers is None: break
                    
                    w = normalize_name(headers.get("White", "Unknown"))
                    b = normalize_name(headers.get("Black", "Unknown"))
                    player_counts[w] += 1
                    player_counts[b] += 1
                    total_games += 1
        except Exception as e:
            logging.error(f"Ошибка чтения файла {file_path}: {e}")
            continue
            
    found_students = {name for name, count in player_counts.items() if count > threshold}
    if forced_list_norm:
        found_students.update(forced_list_norm)
    
    logging.info(f"Всего партий: {total_games}")
    if found_students:
        logging.info(f"Найдено учеников: {len(found_students)}")
        for st in sorted(found_students):
            logging.info(f" [+] {st} (игр: {player_counts.get(st, 0)})")
    else:
        logging.warning("Ученики не найдены.")
        
    return found_students

def process_game_logic(game, engine, config, students_list):
    """
    ОСНОВНАЯ ФУНКЦИЯ АНАЛИЗА ПАРТИИ.
    
    Этапы:
    1. Инициализация (фильтр имен, создание трекеров дебюта).
    2. Походовый перебор партии.
    3. Проверка дебютных принципов (до 15 хода).
    4. Анализ движком (Stockfish) на заданной глубине.
    5. Поиск упущенного мата.
    6. Поиск ошибок (зевков) и классификация тактики (вилки, связки и т.д.).
    7. Запись комментариев в структуру PGN.
    """
    board = game.board()
    node = game
    
    white_raw = game.headers.get('White', '?')
    black_raw = game.headers.get('Black', '?')
    white_name = normalize_name(white_raw)
    black_name = normalize_name(black_raw)
    
    # Проверяем, есть ли наши ученики в этой партии
    analyze_white = white_name in students_list
    analyze_black = black_name in students_list
    
    if not analyze_white and not analyze_black:
        return False # Пропускаем партию
        
    logging.info(f"\n>>> Анализ партии: {white_raw} vs {black_raw}")

    # --- ИНИЦИАЛИЗАЦИЯ ДЕБЮТНОЙ СТАТИСТИКИ ---
    opening_trackers = {}
    
    if analyze_white:
        opening_trackers[chess.WHITE] = {
            "center_control": False,
            "has_castled": False,
            "moved_pieces": set(),
            "target_center": [chess.E4, chess.D4],
            "checked": False
        }
    
    if analyze_black:
        opening_trackers[chess.BLACK] = {
            "center_control": False,
            "has_castled": False,
            "moved_pieces": set(),
            "target_center": [chess.E5, chess.D5],
            "checked": False
        }

    while node.variations:
        next_node = node.variation(0)
        move = next_node.move
        current_turn = board.turn
        
        # --- 1. СБОР ДАННЫХ ДЛЯ ДЕБЮТА ---
        if current_turn in opening_trackers:
            stats = opening_trackers[current_turn]
            piece = board.piece_at(move.from_square)
            
            # Контроль центра пешкой
            if piece and piece.piece_type == chess.PAWN:
                if move.to_square in stats["target_center"]:
                    stats["center_control"] = True
            
            # Рокировка
            if board.is_castling(move):
                stats["has_castled"] = True
            
            # Развитие (запоминаем откуда ходили)
            stats["moved_pieces"].add(move.from_square)
        
        # Проверяем, нужно ли анализировать движком текущий ход
        should_analyze = (current_turn == chess.WHITE and analyze_white) or \
                         (current_turn == chess.BLACK and analyze_black)
            
        if not should_analyze:
            # Если ход соперника, просто обновляем доску, но проверим дебют (если пришло время)
            if current_turn in opening_trackers and not opening_trackers[current_turn]["checked"]:
                if board.fullmove_number == 15:
                    report = classifier.check_opening_principles(opening_trackers[current_turn], current_turn)
                    if report:
                        logging.info(f"   [DEBUT] {white_raw if current_turn else black_raw}: {report}")
                        if next_node.comment: next_node.comment += f" {report}"
                        else: next_node.comment = report
                    opening_trackers[current_turn]["checked"] = True

            board.push(move)
            node = next_node
            continue

        # --- 2. ЗАПУСК ДВИЖКА (STOCKFISH) ---
        try:
            limit = chess.engine.Limit(depth=config["engine_depth"])
            info = engine.analyse(board, limit, multipv=1)
            if isinstance(info, list): info = info[0]
            
            # Защита от пустых PV (пат/мат)
            if "pv" not in info or not info["pv"]:
                board.push(move); node = next_node; continue

            best_move = info["pv"][0]
            
            # Если ученик сыграл по первой линии (лучший ход)
            if move == best_move:
                # Все равно проверяем дебют
                if current_turn in opening_trackers and not opening_trackers[current_turn]["checked"]:
                    if board.fullmove_number == 15:
                        report = classifier.check_opening_principles(opening_trackers[current_turn], current_turn)
                        if report:
                            logging.info(f"   [DEBUT] {white_raw if current_turn else black_raw}: {report}")
                            if next_node.comment: next_node.comment += f" {report}"
                            else: next_node.comment = report
                        opening_trackers[current_turn]["checked"] = True
                
                board.push(move); node = next_node; continue
                
            best_score = info["score"].relative
            mate_issue_found = False
            
            # --- 3. ПРОВЕРКА НА УПУЩЕННЫЙ МАТ ---
            if best_score.is_mate() and 0 < best_score.mate() <= config["mate_depth_trigger"]:
                mate_moves = best_score.mate()
                board.push(move); board.pop() 
                
                # Проверяем оценку ПОСЛЕ хода ученика
                info_user = engine.analyse(board, limit, root_moves=[move])
                if isinstance(info_user, list): info_user = info_user[0]
                user_score_real = info_user["score"].relative
                user_mate = user_score_real.mate()

                # Если мат пропал или стал длиннее
                if not user_score_real.is_mate() or (user_mate > 0 and user_mate > mate_moves):
                    logging.info(f"   [!] Ход {board.fullmove_number}: Упущен МАТ в {mate_moves}. Вариант: {best_move}")
                    next_node.nags.add(chess.pgn.NAG_BLUNDER)
                    variation_root = node.add_variation(best_move)
                    current_var_node = variation_root
                    
                    # Добавляем вариант движка
                    sim_board = board.copy()
                    sim_board.push(best_move)
                    if "pv" in info and len(info["pv"]) > 1:
                        for pv_move in info["pv"][1:]:
                            current_var_node = current_var_node.add_main_variation(pv_move)
                            sim_board.push(pv_move)
                    current_var_node.comment = classifier.get_mate_comment(mate_moves)
                    mate_issue_found = True

            # --- 4. ПРОВЕРКА СТАНДАРТНЫХ ОШИБОК И КЛАССИФИКАЦИЯ ---
            if not mate_issue_found:
                board.push(move); board.pop()
                info_user = engine.analyse(board, limit, root_moves=[move])
                if isinstance(info_user, list): info_user = info_user[0]
                user_score = info_user["score"].relative
                
                score_diff = classifier.calculate_score_difference(best_score, user_score, board.turn, config["mate_score"])
                nag, _ = classifier.get_error_type(score_diff, config)
                
                # Если разница в оценке больше порога ошибки
                if nag and score_diff >= config["error_threshold"]:
                    next_node.nags.add(nag)
                    variation_root = node.add_variation(best_move)
                    
                    tags = []
                    try:
                        # 4.1. Зевки
                        if classifier.is_missed_hanging_piece(board, best_move): tags.append("Не забрал фигуру")
                        elif classifier.is_moving_into_danger(board, move): tags.append("Подставил фигуру")
                        
                        # 4.2. Сложная тактика
                        if classifier.is_double_check(board, best_move): tags.append("Двойной шах")
                        elif classifier.is_discovered_check(board, best_move): tags.append("Вскрытый шах")
                        elif classifier.is_discovered_attack(board, best_move): tags.append("Вскрытое нападение")
                            
                        # 4.3. Базовая тактика
                        if classifier.is_fork(board, best_move): tags.append("Вилка")
                        if classifier.is_skewer(board, best_move): tags.append("Линейный удар")
                        if classifier.is_pin(board, best_move): tags.append("Связка")
                            
                    except Exception as e_class:
                        logging.warning(f"Ошибка классификатора: {e_class}")

                    # Логирование для отладки
                    if tags:
                        logging.info(f"   [x] Ход {board.fullmove_number}: Ошибка. Мотивы: {', '.join(tags)}")
                    else:
                        logging.info(f"   [x] Ход {board.fullmove_number}: Ошибка (Loss: {score_diff})")

                    comment_string = ", ".join(tags)
                    
                    # Добавляем вариант движка
                    current_var_node = variation_root
                    sim_board = board.copy()
                    sim_board.push(best_move)
                    if "pv" in info and len(info["pv"]) > 1:
                        for i, pv_move in enumerate(info["pv"][1:]):
                            if i >= 4: break 
                            current_var_node = current_var_node.add_main_variation(pv_move)
                            sim_board.push(pv_move)
                            
                    # Пишем теги в комментарий
                    if comment_string:
                        current_var_node.comment = comment_string

        except Exception as e:
            logging.error(f"СБОЙ на ходу {board.fullmove_number}: {e}", exc_info=True)
        
        # --- 5. ФИНАЛЬНАЯ ПРОВЕРКА ДЕБЮТА ---
        # (На случай если выше сработал continue)
        if current_turn in opening_trackers and not opening_trackers[current_turn]["checked"]:
            if board.fullmove_number == 15:
                report = classifier.check_opening_principles(opening_trackers[current_turn], current_turn)
                if report:
                    logging.info(f"   [DEBUT] {white_raw if current_turn else black_raw}: {report}")
                    if next_node.comment: next_node.comment += f" {report}"
                    else: next_node.comment = report
                opening_trackers[current_turn]["checked"] = True

        board.push(move)
        node = next_node
    
    return True

def analyze_single_file(input_file, engine, config, students_list):
    """Обрабатывает один PGN файл: читает партии, запускает анализ, сохраняет результат."""
    base_name = os.path.splitext(input_file)[0]
    output_file = f"{base_name}_analyze.pgn"
    logging.info(f"=== Обработка файла: {input_file} ===")

    with open(input_file, "r", encoding="utf-8", errors="replace") as pgn_in, \
         open(output_file, "w", encoding="utf-8") as pgn_out:
        exporter = chess.pgn.FileExporter(pgn_out)
        games_total = 0; games_analyzed = 0
        
        while True:
            try:
                game = chess.pgn.read_game(pgn_in)
            except ValueError as e:
                logging.warning(f"Битая PGN запись: {e}")
                continue
            if game is None: break
            
            games_total += 1
            try:
                was_analyzed = process_game_logic(game, engine, config, students_list)
                if was_analyzed:
                    games_analyzed += 1
                    print(f"\rАнализируем партию {games_analyzed}...", end="")
                game.accept(exporter)
            except Exception as e:
                logging.critical(f"Критическая ошибка в партии: {e}", exc_info=True)
            
        logging.info(f"Файл готов: {output_file}. (Всего: {games_total}, Проверено: {games_analyzed})")
        print(f"\nФайл готов: {output_file}")

def main():
    # Очистка лога при каждом запуске
    with open("chess_log.txt", "w", encoding="utf-8") as f:
        f.write("=== НОВЫЙ ЗАПУСК ===\n")
        
    config = load_config("config.json")
    pgn_files = get_pgn_files()
    
    if not pgn_files:
        logging.warning("PGN файлы не найдены.")
        return
    
    students_list = find_all_students(pgn_files, config)
    if not students_list: return

    try:
        logging.info("Запуск Stockfish...")
        # Запускаем движок
        engine = chess.engine.SimpleEngine.popen_uci(config["stockfish_path"])
        
        # Настраиваем параметры (Ядра и Хеш)
        engine_options = {
            "Threads": config.get("engine_threads", 1), # По умолчанию 1, если в конфиге нет
            "Hash": config.get("engine_hash", 16) # По умолчанию 16 МБ, если в конфиге нет
        }
        engine.configure(engine_options)
        
        logging.info(f"Движок запущен. Threads: {engine_options['Threads']}, Hash: {engine_options['Hash']}MB")

    except Exception as e:
        logging.critical(f"ОШИБКА запуска движка: {e}", exc_info=True)
        return

    for f in pgn_files:
        analyze_single_file(f, engine, config, students_list)
    engine.quit()
    logging.info("ВСЕ ГОТОВО.")

if __name__ == "__main__":
    main()