"""038 — 社区树形版块

- ``forum_boards``：parent_id 自引用，支持「父板块 → 子板块 → 子子板块」。
- ``forum_topics.board_id``：新帖落到叶子版块；存量帖按旧 category 回填。
- 默认树：学术交流（论文沙龙/论文精读/复现与数据、方法与写作、写作与投稿、
  统计与方法、学术生存、组队招募）+ 站务与反馈（站务公告、意见反馈）。

Revision ID: 038_forum_boards
Revises: 037_coin_exchange_settings
Create Date: 2026-11-14
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "038_forum_boards"
down_revision = "037_coin_exchange_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forum_boards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("forum_boards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_forum_boards_tenant_slug"),
    )
    op.create_index("ix_forum_boards_parent_id", "forum_boards", ["parent_id"])
    op.create_index("ix_forum_boards_tenant_id", "forum_boards", ["tenant_id"])
    op.create_index(
        "ix_forum_boards_tenant_parent_sort",
        "forum_boards",
        ["tenant_id", "parent_id", "sort_order"],
    )

    op.add_column("forum_topics", sa.Column("board_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_forum_topics_board_id",
        "forum_topics",
        "forum_boards",
        ["board_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_forum_topics_board_id", "forum_topics", ["board_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE forum_boards ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE forum_boards FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation ON forum_boards
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )

    # 每个租户一套默认树；已有 tenant 都补。
    tenant_rows = bind.execute(sa.text("SELECT id FROM tenants ORDER BY id")).all()
    now = datetime.now(UTC)
    insert_board = sa.text(
        """
        INSERT INTO forum_boards
            (tenant_id, parent_id, slug, name, description, sort_order, is_active, created_at)
        VALUES
            (:tenant_id, :parent_id, :slug, :name, :description, :sort_order, true, :created_at)
        RETURNING id
        """
    )

    def create(tenant_id, parent_id, slug, name, description, sort_order=0):
        return bind.execute(
            insert_board,
            {
                "tenant_id": tenant_id,
                "parent_id": parent_id,
                "slug": slug,
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "created_at": now,
            },
        ).scalar_one()

    for tenant_row in tenant_rows:
        tenant_id = tenant_row[0]
        # FORCE RLS 下迁移角色也需要租户上下文；按当前租户逐套写默认树。
        bind.execute(
            sa.text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        academic = create(tenant_id, None, "academic", "学术交流", "论文、方法、生存与组队", 0)
        paper = create(tenant_id, academic, "paper", "论文沙龙", "逐篇聊论文：方法、结论、复现", 0)
        create(tenant_id, paper, "paper-reading", "论文精读", "精读一篇：问题、方法、证据、局限", 0)
        create(tenant_id, paper, "paper-repro", "复现与数据", "复现实验、数据与代码问题", 1)
        method = create(
            tenant_id, academic, "method", "方法与写作", "选题、统计、审稿意见、拒稿复盘", 1
        )
        create(tenant_id, method, "writing", "写作与投稿", "论文结构、语言、投稿信与返修", 0)
        create(tenant_id, method, "stats", "统计与方法", "统计口径、实验设计与可复现性", 1)
        create(tenant_id, academic, "life", "学术生存", "读研、投稿、毕业与情绪", 2)
        create(tenant_id, academic, "collab", "组队招募", "找合作、找数据、找被试", 3)

        site = create(tenant_id, None, "site", "站务与反馈", "公告、建议、举报与站务", 1)
        create(tenant_id, site, "meta", "站务公告", "官方公告、规则与活动", 0)
        create(tenant_id, site, "feedback", "意见反馈", "产品建议、问题反馈与申诉", 1)

    # 存量帖按旧 category 回填到对应叶子版块；category 同步成 slug，保证新老一致。
    # 回填也必须逐租户设置 RLS 上下文：FORCE RLS 下，一条跨租户 UPDATE
    # 只能看到最后一个 set_config 的租户，其他租户的存量帖会漏回填。
    for tenant_row in tenant_rows:
        bind.execute(
            sa.text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_row[0])},
        )
        bind.execute(
            sa.text(
                """
                UPDATE forum_topics AS t
                SET board_id = b.id,
                    category = b.slug
                FROM forum_boards AS b
                WHERE b.tenant_id = t.tenant_id
                  AND t.tenant_id = :tid
                  AND t.board_id IS NULL
                  AND b.slug = CASE t.category
                    WHEN 'paper' THEN 'paper'
                    WHEN 'discussion' THEN 'paper'
                    WHEN 'method' THEN 'method'
                    WHEN 'question' THEN 'method'
                    WHEN 'life' THEN 'life'
                    WHEN 'collab' THEN 'collab'
                    WHEN 'meta' THEN 'meta'
                    WHEN 'notice' THEN 'meta'
                    WHEN 'suggestion' THEN 'feedback'
                    ELSE NULL
                  END
                """
            ),
            {"tid": tenant_row[0]},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON forum_boards")
        op.execute("ALTER TABLE forum_boards NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE forum_boards DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_forum_topics_board_id", table_name="forum_topics")
    op.drop_constraint("fk_forum_topics_board_id", "forum_topics", type_="foreignkey")
    op.drop_column("forum_topics", "board_id")
    op.drop_index("ix_forum_boards_tenant_parent_sort", table_name="forum_boards")
    op.drop_index("ix_forum_boards_tenant_id", table_name="forum_boards")
    op.drop_index("ix_forum_boards_parent_id", table_name="forum_boards")
    op.drop_table("forum_boards")
