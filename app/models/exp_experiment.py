from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExpExperiment(Base):
    """실험 폴더 위치 레지스트리 (exp-web 스캐너가 갱신).

    각 학습 서버의 training_results/ 를 주기적으로 스캔해 어떤 실험이
    어느 서버에 있는지 기록한다. exp-web은 이 테이블로 통합 목록을 만들고,
    실제 파일은 해당 서버에서 SSH로 pull한다.
    """

    __tablename__ = "exp_experiments"

    exp_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    server_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exp_servers.server_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 폴더명 `...--AUTO-{job_id}` 에서 파싱; 수동 실험은 None
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("jobs.job_id", ondelete="SET NULL"), nullable=True, index=True
    )
    remote_mtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)