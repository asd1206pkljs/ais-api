이 프로젝트는 FastAPI 기반의 API 서버임

반도체 장비의 layout을 관리하는 프로젝트임
db는 postgresql을 사용함

주요기능은 다음과 같음


0. 사용자의 정보를 저장하고 로드해줌
사용자 테이블은 다음과 같음
- user_id (primary key)
- user_name
- user_email
- user_password - hash 필요
- user_company - 회사/소속 (nullable)
- user_credits - int default 0
- joined_at
- last_login_at

현재 요청중인 job의 목록을 저장하는 테이블 
- job_id (primary key)
- user_id
- job_name
- job_path
- created_at
- updated_at
- job_status (string, enum: pending, processing, completed, failed)

1. 사용자가 입력한 장비의 layout에 대한 정보를 db에 저장하고 로드해줌
장비의 layout에 대한 정보는 다음과 같음
- equipment_name
- equipment_id (primary)
- equipment_configuration_file_path
- owner_id 
- viewers // list of users who can view this equipment
- editors // list of users who can edit this equipment
- created_at
- updated_at

장비의 layout은 json 파일로 저장되는데 
single cluster인지 dual cluster인지를 저장하고
각 모듈 (process module, loadlock, loadport, robot, buffer, aligner)의 리스트를 가져야함
각 모듈의 경우 공통적으로는 이 모듈이 어떤 cluster에 속해있는지를 사용자가 입력함 (예: cluster 1, cluster 2)
the equipment configuration file format explained above is as follows 
{
    "equipment_name": "eqp1", 
    "cluster_type": "single_cluster",
    "modules": [
        {
            "module_id": 0,
            "cluster": ["cluster_1"],
        },
        {
            "module_id": 1,
            "cluster": ["cluster_1"],
        },
        {
            "module_id": 2,
            "cluster": ["cluster_1"],
        },
        {
            "module_id": 3,
            "cluster": ["cluster_1"],
        },
        {
            "module_id": 4,
            "cluster": ["cluster_1"],
        },
        {
            "module_id": 5,
            "cluster": ["cluster_1"],
        }
    ]
}

each modules like aligner, loadlock, loadport, robot, buffer, process_module is listed in the table "modules"
the schema is as follows
- module_id (primary key, int)
- module_name (string)
- module_type (string, enum: process_module, loadlock, loadport, robot, buffer, aligner)
- module_subtype (list of string)
- created_at (datetime)
- updated_at (datetime)
- save_status (string, enum: complete, temporary) // denotes if the equipment configuration is complete or temporary

2. stores recipe information 
recipe is divided into flow recipe and process recipe
flow recipe is saved in the flow_recipe table and the schema is as follows 
- flow_recipe_id (primary key)
- flow_recipe_name (string)
- flow_recipe_path (string)
- created_at (datetime)
- updated_at (datetime)
- save_status (string, enum: complete, temporary) // denotes if the flow recipe is complete or temporary

process recipe is saved in the process_recipe table and the schema is as follows 
- process_recipe_id (primary key)
- process_recipe_name (string)
- process_recipe_path (string)
- created_at (datetime)
- updated_at (datetime)
- save_status (string, enum: complete, temporary) // denotes if the process recipe is complete or temporary

the information of flow_recipe is written in json format and saved in the flow_recipe_path in flow recipe db table
the flow recipe file format is as follows 
{
    "flow_recipe_name": "flow_recipe_name",
    "num_process_steps": 4,
    "process_recipe_steps": [
        {
            "step": 1,
            "process_recipe_id": "1" // this is the id of the process_recipe table
        },
        {
            "step": 2,
            "process_recipe_id": "2"
        },
        {
            "step": 3,
            "process_recipe_id": "3"
        },
        {
            "step": 4,
            "process_recipe_id": "4" 
        }
    ] 
}

the information of process_recipe is written in json format and saved in the process_recipe_path in process recipe db table
the process recipe file format is as follows 
{
    "process_recipe_name": "process_recipe_name",
    "user_added_process_modules": [1, 2, 3]
}



## Multi-user security model (2026-10, 과업지시서 B-1~B-5)

Full design + deploy procedure: `docs/SECURITY_MODEL.md`. Short version for anyone touching the code:

- `users.role` (`admin`|`user`) and `users.status` (`pending_approval`|`active`|`disabled`) are the source of truth;
  `ADMIN_EMAILS` only bootstraps. Only `active` accounts pass `get_current_user`. `require_admin` guards `/admin/*`.
- Sharing lives in `resource_shares` (user / group / public principals, view|edit). The old JSONB `viewers`/`editors`
  columns are gone; the Read schemas still expose `viewers`/`editors`, computed from shares (non-owners only see their own id).
- Every access decision goes through `app/services/access.py` (`AccessPolicy`). Recipes and modules carry `owner_id` and
  inherit access from the equipment that references them (`equipment_id`). Admins get metadata only, never content.
- Config files under `FILE_STORAGE_BASE_PATH` are encrypted (`app/services/crypto.py`); `DATA_ENCRYPTION_KEY` is required at startup.
- `audit_logs` is append-only (DB triggers); record actions through `app/services/audit_service.py`.
- Requests (`user_requests`) replace the manual sign-up approval / credit top-up emails; see `app/services/request_service.py`.
- Migration `a7c3e1d9f204` + `python -m app.tasks.migrate_ownership` + `python -m app.tasks.encrypt_files` move existing data over.
- Contracts that must stay: `/jobs/admin/*` and `/simulators/{id}/bundle` for the training launcher (`JobAdminRead` keeps
  `result_path`/`user_email`), and the `--AUTO-<job_id>` experiment folder naming.
