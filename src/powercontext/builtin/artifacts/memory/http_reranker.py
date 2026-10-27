# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTTP cross-encoder reranking for coarse Memory search candidates.

The scoring service answers with a relevance score per candidate rank, but caps how many
candidates one request may carry. This adapter therefore splits the coarse pool into
``batch_size`` slices, keeps the *global* rank of every candidate in the payload, and makes the
final selection over the union of all batch scores. Reranking only reorders and subsets the
pool: the original :class:`MemoryHit` objects, their entry ids, and their entry version ids are
passed through untouched.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

DEFAULT_HTTP_RERANK_POLICY_ID = "http-cross-encoder-v1"

_SCORE_FIELDS = frozenset({"rank", "score"})
_RESPONSE_FIELDS = frozenset({"scores"})


class HTTPMemoryReranker:
    """Score a coarse Memory pool through a batching HTTP cross-encoder.

    One call issues ``ceil(len(candidates) / batch_size)`` POST requests and selects the final
    ``limit`` ranks from the scores of the complete pool, so a high-scoring candidate in a later
    batch competes on equal terms with the first batch.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = DEFAULT_HTTP_RERANK_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint:
            raise ValueError("reranker endpoint must be a non-empty string")  # noqa: TRY003
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("reranker batch_size must be a positive integer")  # noqa: TRY003
        if not isinstance(policy_id, str) or not policy_id:
            raise ValueError("reranker policy_id must be a non-empty string")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Return the globally top-scoring original ranks without changing hit identity."""

        if not isinstance(query, str) or not query:
            raise ValueError("rerank requires a non-empty query")  # noqa: TRY003
        pool = tuple(candidates)
        candidate_count = len(pool)
        if candidate_count < 1:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > candidate_count:
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: dict[int, float] = {}
        requests = 0
        for start in range(0, candidate_count, self._batch_size):
            ranks = tuple(range(start + 1, min(start + self._batch_size, candidate_count) + 1))
            batch = pool[start : start + len(ranks)]
            payload = {
                "query": query,
                "candidates": [
                    {"rank": rank, "text": candidate.text}
                    for rank, candidate in zip(ranks, batch, strict=True)
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
            requests += 1
            scores.update(_validated_scores(response, ranks))

        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _ in ordered[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _validated_scores(response: httpx.Response, ranks: tuple[int, ...]) -> dict[int, float]:
    """Validate one batch response and return its rank-to-score mapping.

    The service may answer in any order, but it must cover exactly the ranks this batch sent,
    once each, with no extra keys anywhere and no non-finite score.
    """

    try:
        data: Any = response.json()
    except ValueError as error:
        raise ValueError("reranker response body is not valid JSON") from error
    if not isinstance(data, dict) or set(data) != _RESPONSE_FIELDS:
        raise ValueError("reranker response must contain exactly a scores array")  # noqa: TRY003
    entries = data["scores"]
    if not isinstance(entries, list):
        raise ValueError("reranker response scores must be an array")  # noqa: TRY003

    expected = set(ranks)
    observed: dict[int, float] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _SCORE_FIELDS:
            raise ValueError("each reranker score must contain exactly rank and score")  # noqa: TRY003
        rank = entry["rank"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("reranker score rank must be an integer")  # noqa: TRY003
        if rank not in expected:
            raise ValueError("reranker score rank is outside the sent batch")  # noqa: TRY003
        if rank in observed:
            raise ValueError("reranker score rank was answered more than once")  # noqa: TRY003
        raw_score = entry["score"]
        if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
            raise ValueError("reranker score must be a number")  # noqa: TRY003
        score = float(raw_score)
        if not math.isfinite(score):
            raise ValueError("reranker score must be a finite number")  # noqa: TRY003
        observed[rank] = score

    if set(observed) != expected:
        raise ValueError("reranker response must cover every rank in the sent batch")  # noqa: TRY003
    return observed


__all__ = ["DEFAULT_HTTP_RERANK_POLICY_ID", "HTTPMemoryReranker"]
