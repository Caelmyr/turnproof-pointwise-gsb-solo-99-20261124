"""Pick a deliverable full spin under the landing-point movement limit.

Every slot contributes one of its own captures. Locked slots keep the manually
locked capture; captures without a base mark cannot be considered. Adjacent
movement reuses the workbench transition metric, including the last slot back
to the first. Among feasible circles we keep as many detail-preferred captures
as possible, then prefer the circle whose largest single step is the smallest.
"""

from image_lab.validation import number

from .inspection import transition


EPSILON = 1e-9


def _candidates(record):
    """Return per-slot eligible captures, plus slots that can never take part."""
    by_slot = [[] for _ in record["slots"]]
    for capture in record["captures"]:
        if capture["mark"] is not None:
            by_slot[capture["slot"]].append(capture)
    options, blocked = [], []
    for index, slot in enumerate(record["slots"]):
        chosen_id = slot["selected"]
        pool = sorted(by_slot[index], key=lambda capture: capture["id"])
        if slot["locked"]:
            locked = next((capture for capture in pool if capture["id"] == chosen_id), None)
            if locked is None:
                blocked.append({
                    "slot": index, "angle": slot["angle"],
                    "reason": "locked_unmarked",
                    "message": f'{slot["angle"]}° 台位已锁定，但锁定原片缺少底座定位点，先补标或解锁。',
                })
                options.append([])
            else:
                options.append([locked])
        elif not pool:
            blocked.append({
                "slot": index, "angle": slot["angle"],
                "reason": "no_marked_capture",
                "message": f'{slot["angle"]}° 台位没有带底座定位点的原片，缺定位点的照片不能凑圈。',
            })
            options.append([])
        else:
            options.append(pool)
    return options, blocked


def _pairs(options, left, right):
    pairs = []
    for capture in options[left]:
        for neighbor in options[right]:
            movement = transition(capture, neighbor)
            if movement is not None:
                pairs.append((capture["id"], neighbor["id"], movement))
    return pairs


def _edge_message(record, left, right):
    first = record["slots"][left]["angle"]
    second = record["slots"][(left + 1) % len(record["slots"])]["angle"]
    tail = "（末张回到首张）" if right == 0 else ""
    return f'{first}° → {second}°{tail}'


def _edge_diagnosis(record, options, limit):
    """Explain structural edges where no eligible pair stays under the limit."""
    total = len(options)
    for left in range(total):
        right = (left + 1) % total
        pairs = [pair for pair in _pairs(options, left, right) if pair[2]["drift"] <= limit + EPSILON]
        if not pairs:
            return {
                "kind": "edge", "slot": left, "angle": record["slots"][left]["angle"],
                "message": f'台位 {_edge_message(record, left, right)} 之间，所有可选原片的落点移动都超过上限 {limit:g}%，这一处接不上。',
            }
    return None


def _conflict_diagnosis(record, options, limit):
    """When every edge has a feasible pair but no full circle exists, locate the tight segment."""
    total = len(options)
    counts = []
    for left in range(total):
        right = (left + 1) % total
        pairs = [pair for pair in _pairs(options, left, right) if pair[2]["drift"] <= limit + EPSILON]
        counts.append(len(pairs))
    left = min(range(total), key=lambda index: counts[index])
    right = (left + 1) % total
    return {
        "kind": "conflict", "slot": left, "angle": record["slots"][left]["angle"],
        "message": f'台位 {_edge_message(record, left, right)} 只有 {counts[left]} 种不超限接法，与前后台位的选择相互冲突，放宽上限或调整这一段的原片。',
    }


def _better(score, best):
    """Rank full, closed rings: preferred count first, then largest step, then ids."""
    if best is None:
        return True
    preferred, worst, ids = score
    best_preferred, best_worst, best_ids = best
    if preferred != best_preferred:
        return preferred > best_preferred
    if worst != best_worst:
        return worst < best_worst
    return ids < best_ids


def _insert(frontier, candidate):
    """Keep the nondominated frontier of partial paths ending at one capture.

    A state dominates another when its preferred count is no smaller and its
    largest step no larger, with a strict edge; on an exact numeric tie the
    smaller path id wins. Worst is a running maximum, so a better prefix worst
    is never discarded when the counts tie: a later, larger step can wash the
    prefix difference out and force the full-ring id tie-break.
    """
    path = tuple(candidate["path"])
    for existing in list(frontier):
        if existing["preferred"] > candidate["preferred"] and existing["worst"] <= candidate["worst"]:
            return
        if existing["preferred"] == candidate["preferred"]:
            if existing["worst"] < candidate["worst"]:
                return
            if existing["worst"] == candidate["worst"]:
                if tuple(existing["path"]) <= path:
                    return
                frontier.remove(existing)
        elif existing["preferred"] < candidate["preferred"] and existing["worst"] >= candidate["worst"]:
            frontier.remove(existing)
    frontier.append(candidate)


def _solve(options, limit):
    """Frontier dynamic programming over the ring, rooted at each slot-0 capture.

    The frontier per end capture is bounded by the distinct (preferred, worst)
    pairs; worst is always one of the finite edge drift values, so the search
    stays small even at 24 slots with three takes each.
    """
    total = len(options)
    best = None
    for root in options[0]:
        states = {root["id"]: [{
            "preferred": 1 if root["preferred"] else 0,
            "worst": 0.0, "path": [root["id"]],
        }]}
        for left in range(1, total):
            following = {}
            for current_id, frontier in states.items():
                current = next(capture for capture in options[left - 1] if capture["id"] == current_id)
                for state in frontier:
                    for neighbor in options[left]:
                        movement = transition(current, neighbor)
                        if movement is None or movement["drift"] > limit + EPSILON:
                            continue
                        _insert(following.setdefault(neighbor["id"], []), {
                            "preferred": state["preferred"] + (1 if neighbor["preferred"] else 0),
                            "worst": max(state["worst"], movement["drift"]),
                            "path": state["path"] + [neighbor["id"]],
                        })
            states = following
            if not states:
                break
        if not states:
            continue
        closing = next(capture for capture in options[0] if capture["id"] == root["id"])
        for current_id, frontier in states.items():
            current = next(capture for capture in options[total - 1] if capture["id"] == current_id)
            for state in frontier:
                movement = transition(current, closing)
                if movement is None or movement["drift"] > limit + EPSILON:
                    continue
                score = (
                    state["preferred"], max(state["worst"], movement["drift"]),
                    tuple(state["path"]),
                )
                if _better(score, best):
                    best = score
    return None if best is None else list(best[2])


def plan(record, raw_limit):
    limit = number(raw_limit, "落点移动上限", 0, 100)
    options, blocked = _candidates(record)
    if blocked:
        return {"feasible": False, "limit": limit, "blocked_slots": blocked,
                "message": blocked[0]["message"]}

    hard_edge = _edge_diagnosis(record, options, limit)
    chosen = _solve(options, limit)
    if chosen is None:
        diagnosis = hard_edge or _conflict_diagnosis(record, options, limit)
        return {"feasible": False, "limit": limit, "blocked_slots": [], "diagnosis": diagnosis,
                "message": diagnosis["message"]}

    captures = {capture["id"]: capture for capture in record["captures"]}
    movements, worst, preferred_count = [], 0.0, 0
    for index, capture_id in enumerate(chosen):
        capture = captures[capture_id]
        neighbor = captures[chosen[(index + 1) % len(chosen)]]
        movement = transition(capture, neighbor)
        movements.append(movement)
        worst = max(worst, movement["drift"])
        preferred_count += 1 if capture["preferred"] else 0
    return {
        "feasible": True, "limit": limit,
        "slots": [{
            "slot": index, "angle": record["slots"][index]["angle"],
            "capture": capture_id, "locked": record["slots"][index]["locked"],
            "preferred": captures[capture_id]["preferred"],
        } for index, capture_id in enumerate(chosen)],
        "movements": movements,
        "preferred_count": preferred_count,
        "worst_drift": worst,
        "message": f'已按上限 {limit:g}% 挑出整圈：细节首选 {preferred_count} 张，最大单步移动 {worst:.2f}%。',
    }


def validate_selection(record, selected):
    """Check a proposed circle against locks, slot ownership and base marks."""
    if not isinstance(selected, list) or len(selected) != len(record["slots"]):
        raise ValueError("封存选择必须覆盖每个台位。")
    captures = {capture["id"]: capture for capture in record["captures"]}
    for index, capture_id in enumerate(selected):
        if not isinstance(capture_id, str) or capture_id not in captures:
            raise ValueError("封存选择包含不存在的原片。")
        capture = captures[capture_id]
        if capture["slot"] != index:
            raise ValueError("封存选择必须使用每个台位自己的原片。")
        if capture["mark"] is None:
            raise ValueError("封存选择不能包含缺定位点的原片。")
        slot = record["slots"][index]
        if slot["locked"] and slot["selected"] != capture_id:
            raise ValueError("锁定台位必须采用锁定的那张原片。")
    return [captures[capture_id] for capture_id in selected]
