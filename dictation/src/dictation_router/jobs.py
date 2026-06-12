from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dictation_router.config.settings import JOBS_DIR, RoutingMode

RECOVERABLE_STATUSES = {
    "recording",
    "recorded",
    "transcribing",
    "transcribed",
    "failed_retryable",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class DictationJob:
    """Durable state for one recording -> transcription -> routing job."""

    def __init__(self, job_dir: Path, data: dict[str, object]) -> None:
        self.job_dir = job_dir
        self.data = data

    @property
    def job_id(self) -> str:
        return str(self.data["job_id"])

    @property
    def status(self) -> str:
        return str(self.data.get("status", "unknown"))

    @property
    def mode(self) -> RoutingMode | None:
        raw = self.data.get("mode")
        if raw is None:
            return None
        try:
            return RoutingMode(str(raw))
        except ValueError:
            return None

    @property
    def audio_path(self) -> Path:
        raw_path = self.data.get("audio_file_path")
        return Path(str(raw_path)) if raw_path else self.job_dir / "audio.wav"

    @property
    def job_json_path(self) -> Path:
        return self.job_dir / "job.json"

    @property
    def status_path(self) -> Path:
        return self.job_dir / "status.txt"

    @property
    def stdout_path(self) -> Path:
        return self.job_dir / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.job_dir / "stderr.log"

    @property
    def partial_transcript_path(self) -> Path:
        return self.job_dir / "transcript.partial.txt"

    @property
    def final_transcript_path(self) -> Path:
        return self.job_dir / "transcript.final.txt"

    @property
    def memory_pressure_path(self) -> Path:
        return self.job_dir / "memory_pressure.txt"

    def update(self, **fields: object) -> None:
        self.data.update(fields)
        self.data["updated_at"] = utc_now_iso()
        self.save()

    def save(self) -> None:
        self.job_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.job_json_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.job_json_path)
        self.status_path.write_text(f"{self.status}\n", encoding="utf-8")

    def attach_audio(self, source_path: Path) -> Path:
        destination = self.job_dir / "audio.wav"
        if source_path.resolve() != destination.resolve():
            shutil.copy2(source_path, destination)
        self.update(
            original_audio_file_path=str(source_path),
            audio_file_path=str(destination),
            status="recorded",
        )
        return destination

    def write_text(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def record_memory_pressure(self) -> None:
        commands = (["memory_pressure"], ["vm_stat"])
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.memory_pressure_path.write_text(
                    f"command={command!r}\nerror={exc}\n",
                    encoding="utf-8",
                )
                continue

            self.memory_pressure_path.write_text(
                "\n".join(
                    [
                        f"command={command!r}",
                        f"exit_code={result.returncode}",
                        "",
                        "stdout:",
                        result.stdout,
                        "",
                        "stderr:",
                        result.stderr,
                    ]
                ),
                encoding="utf-8",
            )
            self.update(memory_pressure_snapshot=str(self.memory_pressure_path))
            return


class JobStore:
    def __init__(self, jobs_dir: Path = JOBS_DIR) -> None:
        self.jobs_dir = jobs_dir

    def create(self, mode: RoutingMode | None) -> DictationJob:
        now = datetime.now(UTC)
        job_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        job_dir = self.jobs_dir / job_id
        job = DictationJob(
            job_dir=job_dir,
            data={
                "job_id": job_id,
                "mode": mode.value if mode is not None else None,
                "target_route": mode.value if mode is not None else None,
                "status": "recording",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "failure_count": 0,
            },
        )
        job.save()
        return job

    def load(self, job_dir: Path) -> DictationJob:
        data = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        return DictationJob(job_dir=job_dir, data=data)

    def recoverable_jobs(self) -> list[DictationJob]:
        if not self.jobs_dir.is_dir():
            return []

        jobs: list[DictationJob] = []
        for job_json in sorted(self.jobs_dir.glob("*/job.json")):
            try:
                job = self.load(job_json.parent)
            except (OSError, json.JSONDecodeError):
                continue

            if job.status in RECOVERABLE_STATUSES:
                jobs.append(job)
        return jobs
