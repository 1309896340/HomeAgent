"""数据库 ORM 模型层（占位示例）。

当前项目尚未引入数据库依赖（如 SQLAlchemy / SQLModel），
此文件仅作为分层占位：后续接入数据库时，ORM 模型类统一放在本层，
由 services 层调用，不直接暴露给 routers / schemas 层。

计划示例（接入 SQLAlchemy 后大致形态）：

    from sqlalchemy.orm import Mapped, mapped_column

    class Item(Base):
        __tablename__ = "items"

        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str]
        description: Mapped[str | None]
"""
