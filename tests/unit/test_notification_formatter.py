from app.services.notifications import NotificationFormatter


def _snapshot(position: int, *, reason: str = "Good evidence"):
    return {
        "position": position,
        "cluster_id": f"cluster-{position}",
        "job_id": f"job-{position}",
        "ranking_id": f"ranking-{position}",
        "title": f"Data <Analyst> & Reporting {position}",
        "company": "Example & Company",
        "location": "Berlin <Remote>",
        "rank_score": 95 - position,
        "fit_score": 90 - position,
        "reason": reason,
        "url": f"https://jobs.example/{position}?a=1&b=2",
    }


def test_plain_text_formatter_preserves_special_characters_safely() -> None:
    chunk = NotificationFormatter(4000).chunks([_snapshot(1)])[0]
    assert "<Analyst> & Reporting" in chunk.text
    assert "parse_mode" not in chunk.text
    assert len(chunk.text) <= 4000


def test_chunking_is_deterministic_and_bounded() -> None:
    snapshots = [_snapshot(index, reason="evidence " * 80) for index in range(1, 9)]
    formatter = NotificationFormatter(700)
    first = formatter.chunks(snapshots)
    second = formatter.chunks(snapshots)
    assert first == second
    assert len(first) > 1
    assert all(len(chunk.text) <= 700 for chunk in first)
    assert [position for chunk in first for position in chunk.positions] == list(range(1, 9))


def test_empty_selection_creates_no_message() -> None:
    assert NotificationFormatter().chunks([]) == ()
