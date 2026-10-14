from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExpServer(Base):
    """학습 서버 레지스트리 (exp-web 뷰어가 SSH로 결과를 pull해 오는 대상).

    exp-web 백엔드가 소유하는 테이블이지만, DB/마이그레이션 관리는
    ais-api(alembic)에서 일원화한다. kind='local'은 exp-web과 같은 호스트
    (SSH 없이 로컬 파일시스템 직접 읽기)를 뜻한다.
    """

    __tablename__ = "exp_servers"

    server_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ssh")  # local | ssh
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="key")  # key | password
    ssh_key_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ssh_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 학습 서버의 ais 저장소 루트 (training_results 의 부모 디렉토리)
    ais_root: Mapped[str] = mapped_column(String(1024), nullable=False, default="~/ais")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )