"""The schema as the MVP shipped it.

Every database created before migrations existed has exactly these tables, made by
`create_all`. Such a database is marked as being here and is never run through this file, so
this is a record of that schema and must not be edited to match a later one.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table('user',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('created_on', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('username')
    )
    # At most one admin (ADR-0008). The predicate is an expression, not text: each database
    # spells "is true" its own way, and generated text carries whichever one generated it.
    is_admin = sa.column('is_admin', sa.Boolean())
    op.create_index('ix_user_single_admin', 'user', ['is_admin'], unique=True,
                    sqlite_where=is_admin.is_(True),
                    postgresql_where=is_admin.is_(True))
    op.create_table('machine',
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('os', sa.Enum('MACOS', 'WINDOWS', 'LINUX', name='ck_machine_os', native_enum=False,
                            create_constraint=True, length=16), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_on', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.user_id'], ),
    sa.PrimaryKeyConstraint('machine_id'),
    sa.UniqueConstraint('token_hash'),
    sa.UniqueConstraint('user_id', 'name', name='uq_machine_user_name')
    )
    op.create_table('skill',
    sa.Column('skill_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=1024), nullable=False),
    sa.Column('origin', sa.String(length=255), nullable=True),
    sa.Column('created_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('pushed_by', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['pushed_by'], ['user.user_id'], ),
    sa.PrimaryKeyConstraint('skill_id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('machine_skill',
    sa.Column('machine_skill_id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('skill_id', sa.Uuid(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_on', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['machine_id'], ['machine.machine_id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['skill_id'], ['skill.skill_id'], ),
    sa.PrimaryKeyConstraint('machine_skill_id'),
    sa.UniqueConstraint('machine_id', 'skill_id', name='uq_machine_skill_machine_skill')
    )
    op.create_table('skill_version',
    sa.Column('skill_version_id', sa.Uuid(), nullable=False),
    sa.Column('skill_id', sa.Uuid(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('frontmatter_json',
              sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'),
              nullable=False),
    sa.Column('created_on', sa.DateTime(timezone=True), nullable=False),
    sa.Column('pushed_by', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['pushed_by'], ['user.user_id'], ),
    sa.ForeignKeyConstraint(['skill_id'], ['skill.skill_id'], ),
    sa.PrimaryKeyConstraint('skill_version_id'),
    sa.UniqueConstraint('skill_id', 'revision', name='uq_skill_version_skill_revision')
    )
    op.create_table('skill_file',
    sa.Column('skill_file_id', sa.Uuid(), nullable=False),
    sa.Column('skill_version_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('executable', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['skill_version_id'], ['skill_version.skill_version_id'],
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('skill_file_id'),
    sa.UniqueConstraint('skill_version_id', 'path', name='uq_skill_file_version_path')
    )
