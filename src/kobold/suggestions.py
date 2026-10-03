from __future__ import annotations

import json
from datetime import datetime, timezone

from kobold.model import Suggestion
from kobold.store import TsvStore

QUESTIONS = ("genre", "name", "authors")
LIBRARY = "*"
ANY_EVIDENCE = "*"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class SuggestionStore(TsvStore):
    fields = ("fingerprint", "question", "answer", "evidence_hash", "asked_at")

    def to_fields(self, key: tuple[str, str], entry: Suggestion) -> dict:
        fingerprint, question = key
        answer = json.dumps(entry.answer, ensure_ascii=False, sort_keys=True)
        return {
            "fingerprint": fingerprint,
            "question": question,
            "answer": answer,
            "evidence_hash": entry.evidence_hash,
            "asked_at": entry.asked_at,
        }

    def from_fields(self, record: dict) -> tuple[tuple[str, str], Suggestion]:
        entry = Suggestion(json.loads(record["answer"]), record["evidence_hash"], record["asked_at"])
        return (record["fingerprint"], record["question"]), entry

    def fingerprint_of(self, key: tuple[str, str]) -> str:
        return key[0]

    def get(self, fingerprint: str, question: str) -> Suggestion | None:
        return self.entries.get((fingerprint, question))

    def set(self, fingerprint: str, question: str, answer: dict, evidence_hash: str) -> None:
        self.entries[(fingerprint, question)] = Suggestion(answer, evidence_hash, now())

    def stale(self, fingerprint: str, question: str, evidence_hash: str) -> bool:
        entry = self.get(fingerprint, question)
        return entry is None or entry.evidence_hash not in (evidence_hash, ANY_EVIDENCE)

    def dismiss(self, fingerprint: str) -> None:
        for question in QUESTIONS:
            self.set(fingerprint, question, {}, ANY_EVIDENCE)

    def drop(self, fingerprint: str, question: str) -> None:
        self.entries.pop((fingerprint, question), None)

    def answers(self, question: str) -> dict[str, dict]:
        return {fp: entry.answer for (fp, q), entry in self.entries.items() if q == question and entry.answer}

    def prune(self, fingerprints: set[str]) -> int:
        return super().prune(fingerprints | {LIBRARY})
