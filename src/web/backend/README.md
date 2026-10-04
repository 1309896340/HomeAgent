后端技术栈:
1. 安装 `uv add fastapi[standard]` 在项目根目录下，依赖统一由根目录的 pyproject.py 管理
2. 目录分为 models, routers, schemas, services，其中 models 存放数据库orm类定义，schemas 存放请求体、响应体、其他结构体等pydantic自定义数据对象，services存放具体业务逻辑文件，routers存放所有路由以及api endpoint
3. 如果有外部配置参数，统一使用环境变量，便于后续docker部署

