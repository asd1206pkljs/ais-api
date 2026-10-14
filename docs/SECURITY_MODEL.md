# ais-api 다중 사용자 보안 모델 (과업 B 구현 요약)

과업지시서 "크로노부스트 고객대상 데모 플랫폼 개발" 의 백엔드 요구(B-1~B-5)를 ais-api에 반영한 내용과
운영 절차를 정리한다. 모든 권한 판단은 서버(서비스 계층)에서 수행하며 화면 제어와 무관하게 적용된다.

## 1. 계정·인증 (B-1)

| 항목 | 구현 |
|---|---|
| 이메일 소유 확인 | 가입 → 인증 메일 → `POST /auth/verify-email` (기존) |
| 계정 상태 | `users.status` = `pending_approval` / `active` / `disabled`. `active`만 로그인·API 호출 가능 |
| 가입 승인 | 인증 완료 시 `SIGNUP_REQUIRE_APPROVAL` 정책 적용. 허용 도메인(`SIGNUP_AUTO_APPROVE_DOMAINS`)이면 즉시 `active`, 아니면 `pending_approval` + 관리자에게 `signup_approval` 요청 생성·메일 통지 |
| 비활성화 | `PATCH /admin/users/{id} {status: disabled}` → `token_version` 증가로 모든 세션 즉시 종료, 로그인 시 403 `Account disabled` |
| 이용약관·개인정보 동의 | 가입 시 `consents: {terms_version, privacy_version}` 필수(`CONSENT_REQUIRED`). `consent_records`에 문서·버전·시각·IP·UA를 append-only 저장. 현재 버전은 `GET /legal/versions`, 재동의는 `POST /users/me/consents` |
| 비밀번호 정책·재설정·세션·로그인 실패 잠금 | 기존 구현 유지 (bcrypt, HttpOnly 쿠키, jti 폐기, token_version, 계정별 lockout) |

## 2. 역할·그룹 (B-2)

* 플랫폼 역할: `users.role` = `admin` | `user`. `.env`의 `ADMIN_EMAILS`는 **부트스트랩용**(마이그레이션이 해당 계정을 admin으로 승격)이며, 이후 역할 변경은 `PATCH /admin/users/{id} {role}`로 수행한다.
* 그룹: `groups` / `group_members(role = admin | member)`. 그룹 생성자는 그룹 admin. 그룹 admin만 구성원 추가(이메일)·역할 변경·제외·그룹 삭제 가능. 마지막 admin은 강등/탈퇴 불가.
* 본인 권한 조회: `GET /users/me/permissions` → 역할, 소속 그룹·그룹 역할, 동의 최신 여부.
* 관리자 전용 라우터 `/admin/*`은 `require_admin` 의존성으로 보호된다.

## 3. 자원 접근 통제·공유 (B-3)

* 자원: equipment, simulator, job, flow_recipe, process_recipe, module. 레시피/모듈에 `owner_id`가 추가되었고, 장비 config가 참조하는 레시피/모듈은 `equipment_id`로 연결되어 **장비 접근 권한을 상속**한다(조회→조회, 편집→편집).
* 공유 테이블 `resource_shares(resource_type, resource_id, principal_type user|group|public, principal_id, permission view|edit)`. 기존 JSONB `viewers`/`editors`는 마이그레이션으로 이 테이블로 옮기고 컬럼은 삭제했다.
* 규칙
  * 소유자만 사용자(이메일)·그룹 공유를 설정·해제한다. 그룹 공유는 본인이 속한 그룹에만 가능.
  * **전체 공개(public)는 플랫폼 관리자만** 설정할 수 있고, 설정 시 소유자에게 메일로 통지된다. 관리자는 타인 자원에 사용자/그룹 공유를 만들 수 없다(내용 접근 우회 방지).
  * job은 조회 공유만 가능. 삭제는 항상 소유자만.
  * 장비 config에 타인의 레시피/모듈 id를 넣어 연결(권한 상속)하는 시도는 422로 거부된다. 편집 권한이 있는 행, 미소유(legacy) 행, 이미 그 장비에 연결된 행만 허용.
* API: `GET/POST /shares/{resource_type}/{id}`, `DELETE /shares/{resource_type}/{id}/{share_id}`. 기존 `/viewers`, `/editors` 엔드포인트는 호환용으로 유지(`"*"`는 관리자만).
* 응답의 `viewers`/`editors`: 소유자에게는 전체 principal 목록, 그 외 사용자에게는 **본인 id와 `*`만** 노출된다(타 사용자 식별정보 비노출).
* 공유 현황: `GET /admin/shares?public_only=true`, `DELETE /admin/shares/{share_id}`.

## 4. 데이터 보호·API 보안 (B-4)

* 저장 암호화: 모든 config JSON(`FILE_STORAGE_BASE_PATH` 하위)은 파일별 DEK(AES-256-GCM)로 암호화되고, DEK는 `DATA_ENCRYPTION_KEY`(KEK)로 wrap되어 헤더에 저장된다(envelope). 파일의 저장 경로가 AAD에 묶여 블롭 치환이 불가능하다. 구현: `app/services/crypto.py`, `file_storage_service.py`.
  * 키 생성: `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
  * 키 회전: 새 키를 `DATA_ENCRYPTION_KEY`, 이전 키를 `DATA_ENCRYPTION_KEYS_PREVIOUS`에 두고 `python -m app.tasks.encrypt_files --rewrap` 실행 후 이전 키 제거.
  * 기존 평문 파일: `python -m app.tasks.encrypt_files` 로 일괄 암호화 후 `ALLOW_PLAINTEXT_FILES=false`.
  * KEK는 `.env`(또는 시크릿 매니저)에만 두고 데이터 디스크와 분리해 보관한다. 외부 KMS 연동은 후속 과제.
* 관리자 원문 접근 차단: 관리자는 자원 **메타데이터**(목록, 이름, 소유자, 상태)만 본다. `/config`, `/copy`, `/generate`, `/bundle`, job 결과(`/results/*`)에는 관리자 우회가 없다. 학습 서버(내부 API 키)는 시스템 주체로서 번들 생성만 수행한다.
* 응답 정보 최소화: 서버 파일 경로 필드(`equipment_configuration_file_path`, `simulator_path`, `*_recipe_path`, 사용자용 `result_path`) 제거. `/generate`는 모델 디렉토리 이름만 반환. 500 응답은 항상 generic 메시지(상세는 서버 로그 + `X-Request-ID`).
* 생성 모델 경로: 장비 이름을 안전 문자로 정규화하고 기준 디렉토리 밖으로 나가는 경로는 거부. 번들은 임시 디렉토리에서 만들어 평문 잔류물을 남기지 않는다.
* 목록 성능: 공유 목록은 자원 N개에 대해 쿼리 1회로 계산(N+1 없음).

## 5. 감사 로그·요청 처리 (B-5)

* `audit_logs`: 행위자(id/email/type), action, outcome, 자원, 대상 사용자, IP, UA, request_id, details(JSONB). DB 트리거가 UPDATE/DELETE/TRUNCATE를 거부한다(append-only). 운영 DB에서는 앱 역할에 `INSERT, SELECT`만 부여하고 마이그레이션은 별도 소유자 역할로 수행할 것을 권장.
  * 기록 대상: 로그인 성공/실패, 로그아웃, 가입/인증, 비밀번호 변경·재설정, 동의, 자원 생성/수정/삭제/복사/생성, config·결과 조회, 공유 부여/해제, 그룹 변경, 요청 제출/결정, 관리자 조치(상태·역할·크레딧), job 상태 변경.
  * 조회: `GET /admin/audit-logs` (actor, action, action_prefix, resource, outcome, 기간, 페이지).
  * 감사 기록 실패는 요청을 실패시키지 않고 error 로그로 남긴다(가용성 우선, 설계 결정).
* 요청 워크플로 `user_requests` (`signup_approval`, `credit`): 사용자 제출 → 정책 자동 처리 또는 관리자 결정 → 이메일 통지.
  * `POST /users/me/credit-request`, `GET /users/me/requests` (사용자), `GET /admin/requests`, `POST /admin/requests/{id}/approve|reject` (관리자).
  * 자동 승인: `CREDIT_REQUEST_AUTO_APPROVE_MAX` 이하이며 최근 `CREDIT_REQUEST_AUTO_APPROVE_WINDOW_DAYS` 내 자동 승인 이력이 없으면 즉시 지급. 가입은 `SIGNUP_AUTO_APPROVE_DOMAINS`.
  * 사용자·유형당 pending 1건(부분 유니크 인덱스), 결정은 조건부 UPDATE로 이중 승인 방지.
* 관리자 콘솔 API: `/admin/users` (목록·검색·상세·역할/상태 변경·크레딧 조정), `/admin/requests`, `/admin/groups`, `/admin/shares`, `/admin/audit-logs`, `/admin/stats`.

## 6. 설정값 (.env)

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATA_ENCRYPTION_KEY` | (필수) | base64 32바이트 KEK. 없으면 기동 실패 |
| `DATA_ENCRYPTION_KEYS_PREVIOUS` | "" | 회전 중 복호화용 이전 키(콤마 구분) |
| `ENCRYPT_DATA_AT_REST` / `ALLOW_PLAINTEXT_FILES` | true / true | 암호화 사용 / 평문 레거시 파일 읽기 허용(이관 후 false) |
| `SIGNUP_REQUIRE_APPROVAL` / `SIGNUP_AUTO_APPROVE_DOMAINS` | true / "" | 가입 승인 정책 |
| `CREDIT_REQUEST_AUTO_APPROVE_MAX` / `..._WINDOW_DAYS` | 0 / 30 | 크레딧 자동 승인 정책 |
| `CREDIT_PURCHASE_ENABLED` | **false** | 결제 연동 없는 모의 구매 엔드포인트. 켜면 누구나 크레딧 즉시 충전 |
| `CONSENT_REQUIRED`, `TERMS_VERSION`, `PRIVACY_VERSION` | true, 2026-10-01 | 동의 정책·문서 버전 |
| `ADMIN_EMAILS` | "" | 부트스트랩 관리자(마이그레이션 시 승격) |
| `ADMIN_NOTIFY_EMAIL` | CONTACT_INBOX_EMAIL | 요청 알림 수신 주소 |
| `DISABLE_RATE_LIMIT` | false | 테스트 전용 |

## 7. 배포·이관 절차 (D-1, D-4)

1. `.env`에 `DATA_ENCRYPTION_KEY` 추가(필수). 필요 시 `SIGNUP_AUTO_APPROVE_DOMAINS`, `ADMIN_NOTIFY_EMAIL`, `CREDIT_PURCHASE_ENABLED` 설정.
2. `PYTHONPATH=/home/ais/ais-api /home/ais/miniconda3/envs/api-server/bin/alembic upgrade head`
   (`a7c3e1d9f204`: 스키마 + 역할/상태/공유 데이터 이관. 운영 DB 사본으로 up/down/up 리허설 완료.)
3. `python -m app.tasks.migrate_ownership` — 장비 config를 읽어 레시피/모듈의 `equipment_id`·`owner_id` 복원. 고아 행은 `--assign-orphans-to <email>`로 귀속. JSON 리포트가 이관 결과서 근거.
4. `python -m app.tasks.encrypt_files` — 평문 config 일괄 암호화 → `ALLOW_PLAINTEXT_FILES=false`.
5. `pm2 restart backend` 후 `curl :8000/openapi.json`, 관리자 로그인 → `/admin/stats` 확인.
6. 프론트엔드(ais-web) 반영 필요 사항은 아래 8절.

## 8. 프론트엔드 영향 (과업 C 연계)

* 가입 폼: `consents: {terms_version, privacy_version}` 전송(`GET /legal/versions`로 현재 버전 조회). 미전송 시 422.
* 가입 인증 후 `pending_approval` 상태의 로그인은 403 `Account awaiting approval` → 안내 화면 필요.
* `/generate` 응답 키가 `output_dir` → `eqp_model`(이름만). `*_path` 필드 제거.
* `POST /users/me/credit-request` 응답이 요청 객체(상태 포함). `GET /users/me/requests`로 처리 상태 표시 가능.
* `viewers`/`editors`는 비소유자에게 본인 id와 `*`만 담긴다(기존 `canEdit` 계산 로직은 그대로 동작).
* 신규 화면용 API: `/groups/*`, `/shares/*`, `/users/me/permissions`, `/admin/*`.

## 9. 알려진 잔여 과제

* 이메일로 그룹 구성원 추가/공유 시 존재 여부가 응답으로 드러난다(초대 수락 흐름으로 바꾸면 해소). 속도 제한·감사 로그로 완화.
* 감사 로그 무결성은 DB 트리거 수준이다. 운영 DB 역할 분리(앱: INSERT/SELECT, 마이그레이션: 소유자)와 외부 보관(WORM)이 후속 과제.
* job_id, module_id는 정수(추측 가능)이나 모든 접근이 서버에서 검증된다. 실험 폴더명 규약(`--AUTO-<job_id>`) 때문에 유지.
* 외부 KMS 연동, 초대 기반 그룹 가입, 자원 삭제 시 사용자 데이터 파일의 즉시 파쇄 정책은 설계 문서(과업 A)에서 확정 필요.
