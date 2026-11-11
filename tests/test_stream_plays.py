from __future__ import annotations

from downtify import stream_plays
from downtify.stream_plays import StreamPlays


def test_queues_once_at_threshold(tmp_path, monkeypatch):
    store = StreamPlays(tmp_path / 'lib.db')
    clock = iter([0, 10, 100, 200, 300])
    monkeypatch.setattr(stream_plays.time, 'time', lambda: next(clock))

    # 10 s after the first start: the same play, not counted.
    assert [store.record('vid', 3) for _ in range(5)] == [
        False,
        False,
        False,
        True,
        False,
    ]
    assert store.plays('vid') == 4
    assert stream_plays.is_play_start('GET', 'bytes=0-')
    assert not stream_plays.is_play_start('GET', 'bytes=5000-')
    assert not stream_plays.is_play_start('HEAD', None)
    assert stream_plays.clamp_threshold('500') == 100
    assert stream_plays.clamp_threshold('x') == 0
