from app.strategy import Arm, choose_arm, pick_losers, score_video, stayed_ratio


def test_stayed_ratio_prefers_engaged_views():
    assert stayed_ratio(1000, 700, 50.0) == 0.7


def test_stayed_ratio_falls_back_to_view_percentage():
    assert stayed_ratio(1000, None, 80.0) == 0.8
    assert stayed_ratio(0, None, None) is None


def test_score_rewards_retention_and_reach():
    low = score_video(100, 30, 40.0)
    high = score_video(10_000, 8_000, 120.0)
    assert 0 <= low < high <= 1


def test_choose_untried_first():
    arms = [Arm(1, [0.8]), Arm(2, [])]
    assert choose_arm(arms) == 2


def test_pending_counts_as_tried():
    arms = [Arm(1, [0.8, 0.7]), Arm(2, [])]
    assert choose_arm(arms, pending={2: 1}) in (1, 2)
    arms = [Arm(1, []), Arm(2, [])]
    assert choose_arm(arms, pending={1: 2, 2: 1}) == 2


def test_choose_exploits_best_with_enough_data():
    arms = [Arm(1, [0.9] * 20), Arm(2, [0.2] * 20)]
    assert choose_arm(arms) == 1


def test_pick_losers_keeps_minimum():
    arms = [Arm(1, [0.9] * 3), Arm(2, [0.3] * 3), Arm(3, [0.85] * 3)]
    assert pick_losers(arms) == [2]
    assert pick_losers(arms[:2]) == []  # houd er altijd 2 over
