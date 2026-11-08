"""New exit IP when YouTube blocks the current one (downtify.ip_rotation).

The control endpoint is never called: ``_post_rotation`` is faked."""

from __future__ import annotations

import pytest

from downtify import ip_rotation
from downtify.ip_rotation import (
    MAX_ROTATIONS_PER_ATTEMPT,
    MAX_ROTATIONS_PER_HOUR,
    current_generation,
    is_bot_check_error,
    rotate_exit_ip,
    run_with_ip_rotation,
)

BOT = 'ERROR: [youtube] x: Sign in to confirm you’re not a bot.'


@pytest.fixture
def posts(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv('DOWNTIFY_IP_ROTATE_URL', 'http://warp:8081/rotate')
    monkeypatch.setattr(ip_rotation, '_generation', 0)
    monkeypatch.setattr(ip_rotation, '_recent', ip_rotation.deque())
    monkeypatch.setattr(ip_rotation, '_post_rotation', calls.append)
    return calls


def test_bot_check_detection():
    assert is_bot_check_error(BOT)
    assert is_bot_check_error("Sign in to confirm you're not a bot")
    assert not is_bot_check_error('HTTP Error 429: Too Many Requests')


def test_rotation_is_off_without_a_url(posts, monkeypatch):
    monkeypatch.delenv('DOWNTIFY_IP_ROTATE_URL')
    assert not rotate_exit_ip(current_generation())
    assert posts == []


def test_a_rotation_bumps_the_generation(posts):
    seen = current_generation()
    assert rotate_exit_ip(seen)
    assert posts == ['http://warp:8081/rotate']
    assert current_generation() == seen + 1


def test_parallel_failures_share_one_rotation(posts):
    seen = current_generation()
    assert rotate_exit_ip(seen)
    # A second download that started on the old IP just retries.
    assert rotate_exit_ip(seen)
    assert len(posts) == 1


def test_the_hourly_budget_stops_rotations(posts):
    for _ in range(MAX_ROTATIONS_PER_HOUR):
        assert rotate_exit_ip(current_generation(), now=1000.0)
    assert not rotate_exit_ip(current_generation(), now=1000.0)
    # An hour later the budget is back.
    assert rotate_exit_ip(current_generation(), now=1000.0 + 3601)


def test_a_failed_rotation_is_not_a_retry(posts, monkeypatch):
    def boom(url):
        raise OSError('connection refused')

    monkeypatch.setattr(ip_rotation, '_post_rotation', boom)
    assert not rotate_exit_ip(current_generation())


def test_run_retries_a_bot_check_on_a_new_ip(posts):
    answers = [RuntimeError(BOT), 'ok']

    def attempt():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert run_with_ip_rotation(attempt) == 'ok'
    assert len(posts) == 1


def test_run_gives_up_after_a_few_new_ips(posts):
    calls = []

    def attempt():
        calls.append(1)
        raise RuntimeError(BOT)

    with pytest.raises(RuntimeError):
        run_with_ip_rotation(attempt)
    assert len(posts) == MAX_ROTATIONS_PER_ATTEMPT
    assert len(calls) == MAX_ROTATIONS_PER_ATTEMPT + 1


def test_run_does_not_retry_other_errors(posts):
    def attempt():
        raise RuntimeError('Video unavailable')

    with pytest.raises(RuntimeError):
        run_with_ip_rotation(attempt)
    assert posts == []


def test_run_retries_a_passing_403_without_a_new_ip(posts):
    waits: list[float] = []
    answers = [RuntimeError('HTTP Error 403: Forbidden'), 'ok']

    def attempt():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert run_with_ip_rotation(attempt, sleep=waits.append) == 'ok'
    assert posts == []
    assert len(waits) == 1


def test_run_gives_up_on_a_lasting_403(posts):
    calls = []

    def attempt():
        calls.append(1)
        raise RuntimeError('HTTP Error 403: Forbidden')

    with pytest.raises(RuntimeError):
        run_with_ip_rotation(attempt, sleep=lambda _s: None)
    assert len(calls) == ip_rotation.MAX_REFUSAL_RETRIES + 1
