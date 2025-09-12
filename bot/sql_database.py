import logging
from typing import List, Optional, Dict, Tuple, TYPE_CHECKING, Union
from datetime import datetime
import os
from urllib.parse import urlparse
from bot.models import Quest, QuestProgress, UserStats, ChannelConfig, DepartedMember, MentorQuest, MentorQuestProgress, MentorshipRelationship

try:
    import asyncpg
except ImportError:
    raise ImportError("asyncpg package is required")

if TYPE_CHECKING:
    try:
        from discord.ext import commands
    except ImportError:
        pass

logger = logging.getLogger(__name__)

class SQLDatabase:
    """Unified SQL database manager for Quest and Leaderboard systems"""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv('DATABASE_URL')
        self.pool: Optional[asyncpg.Pool] = None
        self.bot: Optional['commands.Bot'] = None  # Bot reference for notifications

    async def initialize(self) -> bool:
        """Initialize database connection and create tables"""
        if not self.database_url:
            logger.error("❌ No DATABASE_URL provided. Please set the DATABASE_URL environment variable.")
            return False

        try:
            # Parse database URL to log connection info (without password)
            parsed = urlparse(self.database_url)
            logger.info(f"🔗 Connecting to database: {parsed.hostname}:{parsed.port}/{parsed.path[1:]}")

            # Create connection pool with enhanced settings and SSL for external databases
            import ssl

            # Check if this is an external database (non-localhost)
            parsed = urlparse(self.database_url)
            is_external = parsed.hostname and parsed.hostname not in ['localhost', '127.0.0.1']

            pool_kwargs = {
                'min_size': 2,
                'max_size': 10,
                'command_timeout': 30,
                'server_settings': {'jit': 'off'}
            }

            # Add secure SSL for external databases
            if is_external:
                # Use secure SSL with proper certificate validation
                try:
                    ssl_context = ssl.create_default_context()
                    # Keep default secure settings - DO NOT disable hostname checking or certificate verification
                    # ssl_context.check_hostname = True (default)
                    # ssl_context.verify_mode = ssl.CERT_REQUIRED (default)
                    pool_kwargs['ssl'] = ssl_context
                    logger.info("🔒 Using secure SSL with certificate validation for external database")
                except Exception as ssl_setup_error:
                    logger.error(f"❌ Failed to create secure SSL context: {ssl_setup_error}")
                    # Do not fall back to insecure connection for external databases
                    raise ssl_setup_error

            # Connect to database with secure configuration
            try:
                self.pool = await asyncpg.create_pool(self.database_url, **pool_kwargs)
                if is_external:
                    logger.info("✅ Successfully connected to external database with verified SSL")
                else:
                    logger.info("✅ Successfully connected to local database")
            except Exception as connection_error:
                if is_external:
                    logger.error(f"❌ Failed to connect to external database with secure SSL: {connection_error}")
                    logger.error("🔒 Security policy: External databases MUST use verified SSL connections")
                    raise connection_error
                else:
                    logger.error(f"❌ Failed to connect to local database: {connection_error}")
                    raise connection_error

            await self.create_tables()
            logger.info("✅ Database initialized successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Error initializing database: {e}")
            return False

    async def create_tables(self) -> None:
        """Create all necessary tables for the unified bot"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            # First run migrations for existing tables
            await self._run_migrations(conn)
            # Create quests table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS quests (
                    quest_id VARCHAR(255) PRIMARY KEY,
                    title VARCHAR(500) NOT NULL,
                    description TEXT NOT NULL,
                    creator_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    requirements TEXT DEFAULT '',
                    reward TEXT DEFAULT '',
                    rank VARCHAR(50) DEFAULT 'normal',
                    category VARCHAR(50) DEFAULT 'other',
                    status VARCHAR(50) DEFAULT 'available',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    required_role_ids BIGINT[] DEFAULT ARRAY[]::BIGINT[]
                )
            ''')

            # Create quest progress table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS quest_progress (
                    quest_id VARCHAR(255) NOT NULL,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    approved_at TIMESTAMP,
                    proof_text TEXT DEFAULT '',
                    proof_image_urls TEXT[] DEFAULT ARRAY[]::TEXT[],
                    approval_status VARCHAR(50) DEFAULT '',
                    channel_id BIGINT,
                    PRIMARY KEY (quest_id, user_id)
                )
            ''')

            # Create leaderboard table (unified with quest rewards)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS leaderboard (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    points INTEGER DEFAULT 0 CHECK (points >= 0),
                    total_points_earned INTEGER DEFAULT 0 CHECK (total_points_earned >= 0),
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')

            # Create user stats table (combines quest stats with profile data)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    quests_completed INTEGER DEFAULT 0,
                    quests_accepted INTEGER DEFAULT 0,
                    quests_rejected INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    custom_title VARCHAR(100),
                    status_message VARCHAR(200),
                    preferred_color VARCHAR(7) DEFAULT '#2C3E50',
                    notification_dm BOOLEAN DEFAULT TRUE,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

            # Create channel config table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS channel_config (
                    guild_id BIGINT PRIMARY KEY,
                    quest_list_channel BIGINT,
                    quest_accept_channel BIGINT,
                    quest_submit_channel BIGINT,
                    quest_approval_channel BIGINT,
                    notification_channel BIGINT,
                    retirement_channel BIGINT,
                    rank_request_channel BIGINT,
                    bounty_channel BIGINT,
                    bounty_approval_channel BIGINT
                )
            ''')

            # Add rank_request_channel column if it doesn't exist (for existing databases)
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS rank_request_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add bounty_channel column if it doesn't exist (for existing databases)
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS bounty_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add bounty_approval_channel column if it doesn't exist (for existing databases)
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS bounty_approval_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add funeral_channel column if it doesn't exist (for existing databases)
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS funeral_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add reincarnation_channel column if it doesn't exist
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS reincarnation_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add announcement_channel column if it doesn't exist
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS announcement_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add mentor_quest_channel column if it doesn't exist (for existing databases)
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS mentor_quest_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Add reincarnation_channel column if it doesn't exist (for existing databases)
            try:
                await conn.execute('''
                    ALTER TABLE channel_config 
                    ADD COLUMN IF NOT EXISTS reincarnation_channel BIGINT
                ''')
            except Exception as e:
                logger.debug(f"Column may already exist: {e}")

            # Create quest bookmarks table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS quest_bookmarks (
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    quest_id VARCHAR(255) NOT NULL,
                    bookmarked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT DEFAULT '',
                    PRIMARY KEY (user_id, quest_id)
                )
            ''')

            # Create bounties table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bounties (
                    bounty_id VARCHAR(255) PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    creator_id BIGINT NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    description TEXT NOT NULL,
                    target_username VARCHAR(255) NOT NULL,
                    reward_text TEXT NOT NULL,
                    status VARCHAR(50) DEFAULT 'open',
                    claimed_by_id BIGINT,
                    images TEXT[] DEFAULT ARRAY[]::TEXT[],
                    proof_text TEXT,
                    proof_images TEXT[] DEFAULT ARRAY[]::TEXT[],
                    completion_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claimed_at TIMESTAMP,
                    submitted_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')

            # Create departed_members table for funeral/reincarnation system
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS departed_members (
                    member_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    avatar_url TEXT,
                    highest_role VARCHAR(255),
                    total_points INTEGER DEFAULT 0,
                    join_date TIMESTAMP,
                    leave_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    times_left INTEGER DEFAULT 1,
                    funeral_message TEXT,
                    had_funeral_role BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (member_id, guild_id, leave_date)
                )
            ''')

            # Add the new column if it doesn't exist (for existing databases)
            await conn.execute('''
                ALTER TABLE departed_members 
                ADD COLUMN IF NOT EXISTS had_funeral_role BOOLEAN DEFAULT FALSE
            ''')

            # Create pending_reincarnations table for tracking returning members
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS pending_reincarnations (
                    member_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    return_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notified BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (member_id, guild_id)
                )
            ''')

            # Create mentor_quests table for mentor-given quests
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS mentor_quests (
                    quest_id VARCHAR(255) PRIMARY KEY,
                    title VARCHAR(500) NOT NULL,
                    description TEXT NOT NULL,
                    creator_id BIGINT NOT NULL,
                    disciple_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    requirements TEXT DEFAULT '',
                    reward TEXT DEFAULT '',
                    rank VARCHAR(50) DEFAULT 'normal',
                    category VARCHAR(50) DEFAULT 'other',
                    status VARCHAR(50) DEFAULT 'available',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    required_role_ids BIGINT[] DEFAULT ARRAY[]::BIGINT[]
                )
            ''')

            # Create mentor_quest_progress table for mentor quest submissions
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS mentor_quest_progress (
                    quest_id VARCHAR(255) NOT NULL,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    mentor_id BIGINT NOT NULL,
                    status VARCHAR(50) DEFAULT 'accepted',
                    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    approved_at TIMESTAMP,
                    proof_text TEXT DEFAULT '',
                    proof_image_urls TEXT[] DEFAULT ARRAY[]::TEXT[],
                    channel_id BIGINT,
                    rejection_reason TEXT DEFAULT '',
                    approval_status VARCHAR(50) DEFAULT '',
                    PRIMARY KEY (quest_id, user_id)
                )
            ''')

            # Add missing approval_status column if it doesn't exist (migration)
            await conn.execute('''
                ALTER TABLE mentor_quest_progress 
                ADD COLUMN IF NOT EXISTS approval_status VARCHAR(50) DEFAULT ''
            ''')


            # Create mentorship_relationships table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS mentorship_relationships (
                    mentor_id BIGINT NOT NULL,
                    disciple_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    status VARCHAR(50) DEFAULT 'active',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    mentorship_channel_id BIGINT,
                    starter_quests_removed BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (mentor_id, disciple_id, guild_id)
                )
            ''')

            # Create indexes for better performance
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_quests_guild_status 
                ON quests (guild_id, status)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_quest_progress_user 
                ON quest_progress (user_id, guild_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_leaderboard_guild_points 
                ON leaderboard (guild_id, points DESC)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_leaderboard_username 
                ON leaderboard (guild_id, username)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_bounties_guild_status 
                ON bounties (guild_id, status)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_bounties_creator 
                ON bounties (guild_id, creator_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_bounties_claimed 
                ON bounties (guild_id, claimed_by_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_departed_members_guild_member 
                ON departed_members (guild_id, member_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_departed_members_guild_leave 
                ON departed_members (guild_id, leave_date DESC)
            ''')

            # Create indexes for mentor system tables
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_mentor_quests_guild_mentor 
                ON mentor_quests (guild_id, creator_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_mentor_quests_guild_disciple 
                ON mentor_quests (guild_id, disciple_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_mentor_quest_progress_user 
                ON mentor_quest_progress (user_id, guild_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_mentor_quest_progress_mentor 
                ON mentor_quest_progress (mentor_id, guild_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_mentorship_relationships_mentor 
                ON mentorship_relationships (mentor_id, guild_id)
            ''')

            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_mentorship_relationships_disciple 
                ON mentorship_relationships (disciple_id, guild_id)
            ''')

            # Create trigger to automatically update last_updated
            await conn.execute('''
                CREATE OR REPLACE FUNCTION update_last_updated()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.last_updated = CURRENT_TIMESTAMP;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            ''')

            await conn.execute('''
                DROP TRIGGER IF EXISTS update_leaderboard_timestamp ON leaderboard;
                CREATE TRIGGER update_leaderboard_timestamp
                    BEFORE UPDATE ON leaderboard
                    FOR EACH ROW
                    EXECUTE FUNCTION update_last_updated();
            ''')

            await conn.execute('''
                DROP TRIGGER IF EXISTS update_user_stats_timestamp ON user_stats;
                CREATE TRIGGER update_user_stats_timestamp
                    BEFORE UPDATE ON user_stats
                    FOR EACH ROW
                    EXECUTE FUNCTION update_last_updated();
            ''')
            
            # Create new member onboarding tracking table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS welcome_automation (
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    mentor_id BIGINT,
                    starter_quest_1 VARCHAR(255),
                    starter_quest_2 VARCHAR(255),
                    quest_1_completed BOOLEAN DEFAULT FALSE,
                    quest_2_completed BOOLEAN DEFAULT FALSE,
                    welcome_sent BOOLEAN DEFAULT FALSE,
                    reminder_sent BOOLEAN DEFAULT FALSE,
                    new_disciple_role_awarded BOOLEAN DEFAULT FALSE,
                    mentor_channel_id BIGINT,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')

    async def _run_migrations(self, conn) -> None:
        """Run database migrations for existing tables"""
        try:
            logger.info("🔄 Running database migrations...")
            
            # Check if tables exist before running migrations
            tables_exist = await conn.fetchval('''
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name IN ('quests', 'leaderboard')
                )
            ''')
            
            if not tables_exist:
                logger.info("✅ Fresh database - skipping migrations")
                return
            
            # Migration 1: Add rank column to quests table if it doesn't exist
            try:
                await conn.execute('''
                    ALTER TABLE quests ADD COLUMN IF NOT EXISTS rank VARCHAR(50) DEFAULT 'normal'
                ''')
                logger.info("✅ Migration: Added rank column to quests table")
            except Exception as e:
                logger.warning(f"⚠️ Migration warning for quests.rank: {e}")
            
            # Migration 2: Add display_name column to leaderboard table if it doesn't exist
            try:
                await conn.execute('''
                    ALTER TABLE leaderboard ADD COLUMN IF NOT EXISTS display_name VARCHAR(255)
                ''')
                logger.info("✅ Migration: Added display_name column to leaderboard table")
            except Exception as e:
                logger.warning(f"⚠️ Migration warning for leaderboard.display_name: {e}")
            
            # Migration 3: Backfill display_name from username for existing rows
            try:
                result = await conn.execute('''
                    UPDATE leaderboard 
                    SET display_name = username 
                    WHERE display_name IS NULL OR display_name = ''
                ''')
                logger.info(f"✅ Migration: Backfilled display_name for existing leaderboard entries")
            except Exception as e:
                logger.warning(f"⚠️ Migration warning for display_name backfill: {e}")
            
            # Migration 4: Set display_name as NOT NULL after backfilling (only if all rows have values)
            try:
                # First check if all rows have display_name populated
                null_count = await conn.fetchval('''
                    SELECT COUNT(*) FROM leaderboard WHERE display_name IS NULL OR display_name = ''
                ''')
                if null_count == 0:
                    await conn.execute('''
                        ALTER TABLE leaderboard ALTER COLUMN display_name SET NOT NULL
                    ''')
                    logger.info("✅ Migration: Set display_name as NOT NULL")
                else:
                    logger.warning(f"⚠️ Migration: Cannot set display_name NOT NULL, {null_count} rows still have NULL/empty values")
            except Exception as e:
                logger.warning(f"⚠️ Migration warning for display_name NOT NULL: {e}")
            
            # Migration 5: Ensure user_stats table has proper primary key constraint
            try:
                # Check if primary key constraint exists
                constraint_exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints 
                        WHERE table_name = 'user_stats' 
                        AND constraint_type = 'PRIMARY KEY'
                    )
                ''')
                
                if not constraint_exists:
                    # Add primary key constraint
                    await conn.execute('''
                        ALTER TABLE user_stats ADD PRIMARY KEY (user_id, guild_id)
                    ''')
                    logger.info("✅ Migration: Added primary key constraint to user_stats table")
                else:
                    logger.info("✅ Migration: user_stats primary key constraint already exists")
            except Exception as e:
                logger.warning(f"⚠️ Migration warning for user_stats primary key: {e}")
            
            # Migration 6: Ensure leaderboard table has proper primary key constraint
            try:
                # Check if primary key constraint exists on leaderboard table
                leaderboard_constraint_exists = await conn.fetchval('''
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints 
                        WHERE table_name = 'leaderboard' 
                        AND constraint_type = 'PRIMARY KEY'
                    )
                ''')
                
                if not leaderboard_constraint_exists:
                    # Add primary key constraint to leaderboard
                    await conn.execute('''
                        ALTER TABLE leaderboard ADD PRIMARY KEY (guild_id, user_id)
                    ''')
                    logger.info("✅ Migration: Added primary key constraint to leaderboard table")
                else:
                    logger.info("✅ Migration: leaderboard primary key constraint already exists")
            except Exception as e:
                logger.warning(f"⚠️ Migration warning for leaderboard primary key: {e}")
            
            logger.info("✅ Database migrations completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Error running database migrations: {e}")
            # Don't fail initialization on migration errors, just log them

    async def execute_query(self, query: str, *args):
        """Execute a query directly"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def _reset_connection_pool(self):
        """Reset the connection pool to clear cached statements"""
        try:
            if self.pool:
                await self.pool.close()
                # Recreate the pool with same settings
                parsed = urlparse(self.database_url)
                is_external = parsed.hostname and parsed.hostname not in ['localhost', '127.0.0.1']

                pool_kwargs = {
                    'min_size': 2,
                    'max_size': 10,
                    'command_timeout': 30,
                    'server_settings': {'jit': 'off'}
                }

                if is_external:
                    import ssl
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                    pool_kwargs['ssl'] = ssl_context

                self.pool = await asyncpg.create_pool(self.database_url, **pool_kwargs)
                logger.info("✅ Connection pool reset successfully")
        except asyncpg.ConnectionDoesNotExistError as e:
            logger.error(f"❌ Connection pool connection error: {e}")
        except asyncpg.InterfaceError as e:
            logger.error(f"❌ Connection pool interface error: {e}")
        except Exception as e:
            logger.error(f"❌ Error resetting connection pool: {e}")

    # Quest-related methods
    async def save_quest(self, quest: Quest):
        """Save a quest to the database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO quests (quest_id, title, description, creator_id, guild_id, 
                                  requirements, reward, rank, category, status, created_at, required_role_ids)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (quest_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    requirements = EXCLUDED.requirements,
                    reward = EXCLUDED.reward,
                    rank = EXCLUDED.rank,
                    category = EXCLUDED.category,
                    status = EXCLUDED.status,
                    required_role_ids = EXCLUDED.required_role_ids
            ''', quest.quest_id, quest.title, quest.description, quest.creator_id, quest.guild_id,
                quest.requirements, quest.reward, quest.rank, quest.category, quest.status, 
                quest.created_at, quest.required_role_ids)

    async def get_quest(self, quest_id: str) -> Optional[Quest]:
        """Get a quest by ID"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM quests WHERE quest_id = $1', quest_id)
            if row:
                return Quest(
                    quest_id=row['quest_id'],
                    title=row['title'],
                    description=row['description'],
                    creator_id=row['creator_id'],
                    guild_id=row['guild_id'],
                    requirements=row['requirements'] or '',
                    reward=row['reward'] or '',
                    rank=row['rank'] or 'normal',
                    category=row['category'] or 'other',
                    status=row['status'] or 'available',
                    created_at=row['created_at'],
                    required_role_ids=list(row['required_role_ids']) if row['required_role_ids'] else []
                )
            return None

    async def get_guild_quests(self, guild_id: int, status: Optional[str] = None) -> List[Quest]:
        """Get all quests for a guild, optionally filtered by status"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            if status:
                rows = await conn.fetch('SELECT * FROM quests WHERE guild_id = $1 AND status = $2 ORDER BY created_at DESC', guild_id, status)
            else:
                rows = await conn.fetch('SELECT * FROM quests WHERE guild_id = $1 ORDER BY created_at DESC', guild_id)

            quests = []
            for row in rows:
                quest = Quest(
                    quest_id=row['quest_id'],
                    title=row['title'],
                    description=row['description'],
                    creator_id=row['creator_id'],
                    guild_id=row['guild_id'],
                    requirements=row['requirements'] or '',
                    reward=row['reward'] or '',
                    rank=row['rank'] or 'normal',
                    category=row['category'] or 'other',
                    status=row['status'] or 'available',
                    created_at=row['created_at'],
                    required_role_ids=list(row['required_role_ids']) if row['required_role_ids'] else []
                )
                quests.append(quest)
            return quests

    async def save_quest_progress(self, progress: QuestProgress):
        """Save quest progress to the database"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO quest_progress (quest_id, user_id, guild_id, status, accepted_at, 
                                          completed_at, approved_at, proof_text, proof_image_urls, 
                                          approval_status, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (quest_id, user_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    completed_at = EXCLUDED.completed_at,
                    approved_at = EXCLUDED.approved_at,
                    proof_text = EXCLUDED.proof_text,
                    proof_image_urls = EXCLUDED.proof_image_urls,
                    approval_status = EXCLUDED.approval_status,
                    channel_id = EXCLUDED.channel_id
            ''', progress.quest_id, progress.user_id, progress.guild_id, progress.status,
                progress.accepted_at, progress.completed_at, progress.approved_at, 
                progress.proof_text, progress.proof_image_urls, progress.approval_status, 
                progress.channel_id)

    async def get_user_quest_progress(self, user_id: int, quest_id: str) -> Optional[QuestProgress]:
        """Get quest progress for a specific user and quest"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM quest_progress WHERE user_id = $1 AND quest_id = $2', user_id, quest_id)
            if row:
                return QuestProgress(
                    quest_id=row['quest_id'],
                    user_id=row['user_id'],
                    guild_id=row['guild_id'],
                    status=row['status'],
                    accepted_at=row['accepted_at'],
                    completed_at=row['completed_at'],
                    approved_at=row['approved_at'],
                    proof_text=row['proof_text'] or '',
                    proof_image_urls=list(row['proof_image_urls']) if row['proof_image_urls'] else [],
                    approval_status=row['approval_status'] or '',
                    channel_id=row['channel_id']
                )
            return None

    async def get_pending_quest_approvals(self, guild_id: int) -> List[dict]:
        """Get all quest submissions pending approval"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT qp.*, q.title, q.description, q.reward, q.creator_id, q.rank
                FROM quest_progress qp
                JOIN quests q ON qp.quest_id = q.quest_id
                WHERE qp.guild_id = $1 AND qp.status = 'completed'
                ORDER BY qp.completed_at DESC
            ''', guild_id)

            pending_approvals = []
            for row in rows:
                approval_data = {
                    'quest_id': row['quest_id'],
                    'quest_title': row['title'],
                    'quest_description': row['description'],
                    'quest_reward': row['reward'],
                    'quest_creator_id': row['creator_id'],
                    'quest_rank': row['rank'],
                    'user_id': row['user_id'],
                    'completed_at': row['completed_at'],
                    'proof_text': row['proof_text'] or '',
                    'proof_image_urls': list(row['proof_image_urls']) if row['proof_image_urls'] else [],
                    'channel_id': row['channel_id']
                }
                pending_approvals.append(approval_data)
            return pending_approvals

    # Leaderboard-related methods
    async def add_member(self, guild_id: int, user_id: int, username: str):
        """Add a member to the leaderboard (preserves existing points)"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO leaderboard (guild_id, user_id, username, display_name, points)
                VALUES ($1, $2, $3, $3, 0)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    display_name = EXCLUDED.display_name
                    -- Keep existing points, only update username and display_name
            ''', guild_id, user_id, username)

    async def update_points(self, guild_id: int, user_id: int, points_change: int, username: str) -> bool:
        """Update points for a user (can be positive or negative)"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                # First ensure the user exists in leaderboard
                await conn.execute('''
                    INSERT INTO leaderboard (guild_id, user_id, username, display_name, points)
                    VALUES ($1, $2, $3, $3, 0)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        display_name = EXCLUDED.display_name
                ''', guild_id, user_id, username)

                # Update points
                await conn.execute('''
                    UPDATE leaderboard 
                    SET points = GREATEST(0, points + $3)
                    WHERE guild_id = $1 AND user_id = $2
                ''', guild_id, user_id, points_change)

                return True
        except Exception as e:
            logger.error(f"Error updating points: {e}")
            return False

    async def set_user_points(self, guild_id: int, user_id: int, points: int, username: str) -> bool:
        """Set exact points for a user (used for bulk imports)"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                # Insert or update user with exact points value
                await conn.execute('''
                    INSERT INTO leaderboard (guild_id, user_id, username, display_name, points, last_updated)
                    VALUES ($1, $2, $3, $3, $4, CURRENT_TIMESTAMP)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        display_name = EXCLUDED.display_name,
                        points = EXCLUDED.points,
                        last_updated = CURRENT_TIMESTAMP
                ''', guild_id, user_id, username, points)

                return True
        except Exception as e:
            logger.error(f"Error setting user points: {e}")
            return False

    async def get_user_stats(self, user_id: int, guild_id: int) -> Optional[UserStats]:
        """Get user statistics"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM user_stats WHERE user_id = $1 AND guild_id = $2', user_id, guild_id)
            if row:
                return UserStats(
                    user_id=row['user_id'],
                    guild_id=row['guild_id'],
                    quests_completed=row['quests_completed'],
                    quests_accepted=row['quests_accepted'],
                    quests_rejected=row['quests_rejected'],
                    last_updated=row['last_updated']
                )
            return None

    async def save_user_stats(self, stats: UserStats):
        """Save user statistics"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO user_stats (user_id, guild_id, quests_completed, quests_accepted, 
                                      quests_rejected, last_updated)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (user_id, guild_id) DO UPDATE SET
                    quests_completed = EXCLUDED.quests_completed,
                    quests_accepted = EXCLUDED.quests_accepted,
                    quests_rejected = EXCLUDED.quests_rejected,
                    last_updated = EXCLUDED.last_updated
            ''', stats.user_id, stats.guild_id, stats.quests_completed, 
                stats.quests_accepted, stats.quests_rejected, stats.last_updated)

    async def get_guild_leaderboard(self, guild_id: int, limit: int = 10) -> List[UserStats]:
        """Get guild leaderboard"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT us.*, lb.points 
                FROM user_stats us
                JOIN leaderboard lb ON us.user_id = lb.user_id AND us.guild_id = lb.guild_id
                WHERE us.guild_id = $1
                ORDER BY lb.points DESC
                LIMIT $2
            ''', guild_id, limit)

            stats = []
            for row in rows:
                stat = UserStats(
                    user_id=row['user_id'],
                    guild_id=row['guild_id'],
                    quests_completed=row['quests_completed'],
                    quests_accepted=row['quests_accepted'],
                    quests_rejected=row['quests_rejected'],
                    last_updated=row['last_updated']
                )
                stats.append(stat)
            return stats

    async def get_total_guild_stats(self, guild_id: int) -> Dict[str, int]:
        """Get total guild statistics"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT 
                    SUM(quests_completed) as total_completed,
                    SUM(quests_accepted) as total_accepted,
                    SUM(quests_rejected) as total_rejected,
                    COUNT(*) as total_users
                FROM user_stats WHERE guild_id = $1
            ''', guild_id)

            if row:
                return {
                    'total_completed': row['total_completed'] or 0,
                    'total_accepted': row['total_accepted'] or 0,
                    'total_rejected': row['total_rejected'] or 0,
                    'total_users': row['total_users'] or 0
                }
            return {'total_completed': 0, 'total_accepted': 0, 'total_rejected': 0, 'total_users': 0}

    # Channel config methods
    async def save_channel_config(self, config: ChannelConfig):
        """Save channel configuration"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO channel_config (guild_id, quest_list_channel, quest_accept_channel,
                                          quest_submit_channel, quest_approval_channel, notification_channel,
                                          retirement_channel, rank_request_channel, bounty_channel, bounty_approval_channel,
                                          mentor_quest_channel, funeral_channel, reincarnation_channel, announcement_channel)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (guild_id) DO UPDATE SET
                    quest_list_channel = EXCLUDED.quest_list_channel,
                    quest_accept_channel = EXCLUDED.quest_accept_channel,
                    quest_submit_channel = EXCLUDED.quest_submit_channel,
                    quest_approval_channel = EXCLUDED.quest_approval_channel,
                    notification_channel = EXCLUDED.notification_channel,
                    retirement_channel = EXCLUDED.retirement_channel,
                    rank_request_channel = EXCLUDED.rank_request_channel,
                    bounty_channel = EXCLUDED.bounty_channel,
                    bounty_approval_channel = EXCLUDED.bounty_approval_channel,
                    mentor_quest_channel = EXCLUDED.mentor_quest_channel,
                    funeral_channel = EXCLUDED.funeral_channel,
                    reincarnation_channel = EXCLUDED.reincarnation_channel,
                    announcement_channel = EXCLUDED.announcement_channel
            ''', config.guild_id, config.quest_list_channel, config.quest_accept_channel,
                config.quest_submit_channel, config.quest_approval_channel, config.notification_channel,
                config.retirement_channel, config.rank_request_channel, config.bounty_channel, config.bounty_approval_channel,
                config.mentor_quest_channel, config.funeral_channel, config.reincarnation_channel, config.announcement_channel)

    async def get_channel_config(self, guild_id: int) -> Optional[ChannelConfig]:
        """Get channel configuration for a guild"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('SELECT * FROM channel_config WHERE guild_id = $1', guild_id)
                if row:
                    return ChannelConfig(
                        guild_id=row['guild_id'],
                        quest_list_channel=row['quest_list_channel'],
                        quest_accept_channel=row['quest_accept_channel'],
                        quest_submit_channel=row['quest_submit_channel'],
                        quest_approval_channel=row['quest_approval_channel'],
                        notification_channel=row['notification_channel'],
                        retirement_channel=row['retirement_channel'],
                        rank_request_channel=row['rank_request_channel'] if 'rank_request_channel' in row and row['rank_request_channel'] else None,
                        bounty_channel=row['bounty_channel'] if 'bounty_channel' in row and row['bounty_channel'] else None,
                        bounty_approval_channel=row['bounty_approval_channel'] if 'bounty_approval_channel' in row and row['bounty_approval_channel'] else None,
                        mentor_quest_channel=row['mentor_quest_channel'] if 'mentor_quest_channel' in row and row['mentor_quest_channel'] else None,
                        funeral_channel=row['funeral_channel'] if 'funeral_channel' in row and row['funeral_channel'] else None,
                        reincarnation_channel=row['reincarnation_channel'] if 'reincarnation_channel' in row and row['reincarnation_channel'] else None,
                        announcement_channel=row['announcement_channel'] if 'announcement_channel' in row and row['announcement_channel'] else None
                    )
                return None
        except asyncpg.exceptions.InvalidCachedStatementError:
            logger.warning("⚠️ Cached statement error, resetting connection pool...")
            # Reset the connection to clear cached statements
            await self._reset_connection_pool()
            # Retry the operation
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('SELECT * FROM channel_config WHERE guild_id = $1', guild_id)
                if row:
                    return ChannelConfig(
                        guild_id=row['guild_id'],
                        quest_list_channel=row['quest_list_channel'],
                        quest_accept_channel=row['quest_accept_channel'],
                        quest_submit_channel=row['quest_submit_channel'],
                        quest_approval_channel=row['quest_approval_channel'],
                        notification_channel=row['notification_channel'],
                        retirement_channel=row['retirement_channel'],
                        rank_request_channel=row['rank_request_channel'] if 'rank_request_channel' in row and row['rank_request_channel'] else None,
                        bounty_channel=row['bounty_channel'] if 'bounty_channel' in row and row['bounty_channel'] else None,
                        bounty_approval_channel=row['bounty_approval_channel'] if 'bounty_approval_channel' in row and row['bounty_approval_channel'] else None,
                        mentor_quest_channel=row['mentor_quest_channel'] if 'mentor_quest_channel' in row and row['mentor_quest_channel'] else None,
                        funeral_channel=row['funeral_channel'] if 'funeral_channel' in row and row['funeral_channel'] else None,
                        reincarnation_channel=row['reincarnation_channel'] if 'reincarnation_channel' in row and row['reincarnation_channel'] else None,
                        announcement_channel=row['announcement_channel'] if 'announcement_channel' in row and row['announcement_channel'] else None
                    )
                return None

    async def delete_all_quests(self, guild_id: int) -> Dict[str, int]:
        """Delete all quests for a specific guild and return deletion counts"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Get counts before deletion
                quest_count = await conn.fetchval('SELECT COUNT(*) FROM quests WHERE guild_id = $1', guild_id)
                progress_count = await conn.fetchval('SELECT COUNT(*) FROM quest_progress WHERE guild_id = $1', guild_id)
                team_progress_count = await conn.fetchval('SELECT COUNT(*) FROM team_progress WHERE guild_id = $1', guild_id)

                # Delete all related data (CASCADE should handle this, but explicit is better)
                await conn.execute('DELETE FROM team_progress WHERE guild_id = $1', guild_id)
                await conn.execute('DELETE FROM quest_progress WHERE guild_id = $1', guild_id)
                await conn.execute('DELETE FROM quests WHERE guild_id = $1', guild_id)

                return {
                    'quests_deleted': quest_count,
                    'quest_progress_deleted': progress_count,
                    'team_progress_deleted': team_progress_count
                }

    # Departed Members methods for Funeral/Reincarnation system
    async def save_departed_member(self, departed_member: DepartedMember) -> bool:
        """Save a departed member to the database"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO departed_members (member_id, guild_id, username, display_name, avatar_url,
                                                highest_role, total_points, join_date, leave_date, times_left, funeral_message, had_funeral_role, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (member_id, guild_id, leave_date) DO UPDATE SET
                        username = EXCLUDED.username,
                        display_name = EXCLUDED.display_name,
                        avatar_url = EXCLUDED.avatar_url,
                        highest_role = EXCLUDED.highest_role,
                        total_points = EXCLUDED.total_points,
                        times_left = EXCLUDED.times_left,
                        funeral_message = EXCLUDED.funeral_message,
                        had_funeral_role = EXCLUDED.had_funeral_role
                ''', departed_member.member_id, departed_member.guild_id, departed_member.username,
                    departed_member.display_name, departed_member.avatar_url, departed_member.highest_role,
                    departed_member.total_points, departed_member.join_date, departed_member.leave_date,
                    departed_member.times_left, departed_member.funeral_message, departed_member.had_funeral_role, departed_member.created_at)
                return True
        except Exception as e:
            logger.error(f"❌ Error saving departed member: {e}")
            return False

    async def get_departed_member(self, member_id: int, guild_id: int) -> Optional[DepartedMember]:
        """Get the most recent departure record for a member"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM departed_members 
                WHERE member_id = $1 AND guild_id = $2 
                ORDER BY leave_date DESC 
                LIMIT 1
            ''', member_id, guild_id)

            if row:
                return DepartedMember(
                    member_id=row['member_id'],
                    guild_id=row['guild_id'],
                    username=row['username'],
                    display_name=row['display_name'],
                    avatar_url=row['avatar_url'],
                    highest_role=row['highest_role'],
                    total_points=row['total_points'],
                    join_date=row['join_date'],
                    leave_date=row['leave_date'],
                    times_left=row['times_left'],
                    funeral_message=row['funeral_message'],
                    had_funeral_role=row['had_funeral_role'] if 'had_funeral_role' in row and row['had_funeral_role'] is not None else False,
                    created_at=row['created_at']
                )
            return None

    async def update_departed_member_return(self, member_id: int, guild_id: int) -> bool:
        """Update departed member record when they return (increment times_left)"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                # Update the most recent departure record
                result = await conn.execute('''
                    UPDATE departed_members 
                    SET times_left = times_left + 1 
                    WHERE member_id = $1 AND guild_id = $2 
                    AND leave_date = (
                        SELECT MAX(leave_date) 
                        FROM departed_members 
                        WHERE member_id = $1 AND guild_id = $2
                    )
                ''', member_id, guild_id)
                return result != "UPDATE 0"
        except Exception as e:
            logger.error(f"❌ Error updating departed member return: {e}")
            return False

    # Pending reincarnations methods
    async def add_pending_reincarnation(self, member_id: int, guild_id: int) -> bool:
        """Add a member to pending reincarnations"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO pending_reincarnations (member_id, guild_id, return_date, notified)
                    VALUES ($1, $2, CURRENT_TIMESTAMP, FALSE)
                    ON CONFLICT (member_id, guild_id) DO UPDATE SET
                        return_date = CURRENT_TIMESTAMP,
                        notified = FALSE
                ''', member_id, guild_id)
                return True
        except Exception as e:
            logger.error(f"❌ Error adding pending reincarnation: {e}")
            return False

    async def get_pending_reincarnation(self, member_id: int, guild_id: int) -> Optional[dict]:
        """Get pending reincarnation record"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT * FROM pending_reincarnations 
                    WHERE member_id = $1 AND guild_id = $2
                ''', member_id, guild_id)

                if row:
                    return {
                        'member_id': row['member_id'],
                        'guild_id': row['guild_id'],
                        'return_date': row['return_date'],
                        'notified': row['notified']
                    }
                return None
        except Exception as e:
            logger.error(f"❌ Error getting pending reincarnation: {e}")
            return None

    async def mark_reincarnation_notified(self, member_id: int, guild_id: int) -> bool:
        """Mark reincarnation as notified and remove from pending"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    DELETE FROM pending_reincarnations 
                    WHERE member_id = $1 AND guild_id = $2
                ''', member_id, guild_id)
                return True
        except Exception as e:
            logger.error(f"❌ Error marking reincarnation notified: {e}")
            return False

    # Mentor quest system database operations
    async def save_mentor_quest(self, quest: 'MentorQuest') -> bool:
        """Save a mentor quest to the database"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO mentor_quests (quest_id, title, description, creator_id, disciple_id, guild_id,
                                             requirements, reward, rank, category, status, created_at, required_role_ids)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (quest_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        requirements = EXCLUDED.requirements,
                        reward = EXCLUDED.reward,
                        rank = EXCLUDED.rank,
                        category = EXCLUDED.category,
                        status = EXCLUDED.status,
                        required_role_ids = EXCLUDED.required_role_ids
                ''', quest.quest_id, quest.title, quest.description, quest.creator_id, quest.disciple_id,
                    quest.guild_id, quest.requirements, quest.reward, quest.rank, quest.category,
                    quest.status, quest.created_at, quest.required_role_ids)
                return True
        except Exception as e:
            logger.error(f"❌ Error saving mentor quest: {e}")
            return False

    async def get_mentor_quest(self, quest_id: str) -> Optional['MentorQuest']:
        """Get a mentor quest by ID"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('SELECT * FROM mentor_quests WHERE quest_id = $1', quest_id)
                if row:
                    return MentorQuest(
                        quest_id=row['quest_id'],
                        title=row['title'],
                        description=row['description'],
                        creator_id=row['creator_id'],
                        disciple_id=row['disciple_id'],
                        guild_id=row['guild_id'],
                        requirements=row['requirements'],
                        reward=row['reward'],
                        rank=row['rank'],
                        category=row['category'],
                        status=row['status'],
                        created_at=row['created_at'],
                        required_role_ids=list(row['required_role_ids']) if row['required_role_ids'] else []
                    )
                return None
        except Exception as e:
            logger.error(f"❌ Error getting mentor quest: {e}")
            return None

    async def save_mentor_quest_progress(self, progress: 'MentorQuestProgress') -> bool:
        """Save mentor quest progress to the database"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO mentor_quest_progress (quest_id, user_id, guild_id, mentor_id, status, 
                                                     accepted_at, completed_at, approved_at, proof_text, 
                                                     proof_image_urls, channel_id, rejection_reason)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (quest_id, user_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        completed_at = EXCLUDED.completed_at,
                        approved_at = EXCLUDED.approved_at,
                        proof_text = EXCLUDED.proof_text,
                        proof_image_urls = EXCLUDED.proof_image_urls,
                        rejection_reason = EXCLUDED.rejection_reason
                ''', progress.quest_id, progress.user_id, progress.guild_id, progress.mentor_id,
                    progress.status, progress.accepted_at, progress.completed_at, progress.approved_at,
                    progress.proof_text, progress.proof_image_urls, progress.channel_id, progress.rejection_reason)
                return True
        except Exception as e:
            logger.error(f"❌ Error saving mentor quest progress: {e}")
            return False

    async def get_mentor_quest_progress(self, user_id: int, quest_id: str) -> Optional['MentorQuestProgress']:
        """Get mentor quest progress for a user"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT * FROM mentor_quest_progress 
                    WHERE user_id = $1 AND quest_id = $2
                ''', user_id, quest_id)
                if row:
                    return MentorQuestProgress(
                        quest_id=row['quest_id'],
                        user_id=row['user_id'],
                        guild_id=row['guild_id'],
                        mentor_id=row['mentor_id'],
                        status=row['status'],
                        accepted_at=row['accepted_at'],
                        completed_at=row['completed_at'],
                        approved_at=row['approved_at'],
                        proof_text=row['proof_text'],
                        proof_image_urls=list(row['proof_image_urls']) if row['proof_image_urls'] else [],
                        channel_id=row['channel_id'],
                        rejection_reason=row['rejection_reason']
                    )
                return None
        except Exception as e:
            logger.error(f"❌ Error getting mentor quest progress: {e}")
            return None

    async def save_mentorship_relationship(self, relationship: 'MentorshipRelationship') -> bool:
        """Save mentorship relationship to the database"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO mentorship_relationships (mentor_id, disciple_id, guild_id, status, 
                                                        started_at, ended_at, mentorship_channel_id, 
                                                        starter_quests_removed)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (mentor_id, disciple_id, guild_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        ended_at = EXCLUDED.ended_at,
                        mentorship_channel_id = EXCLUDED.mentorship_channel_id,
                        starter_quests_removed = EXCLUDED.starter_quests_removed
                ''', relationship.mentor_id, relationship.disciple_id, relationship.guild_id, 
                    relationship.status, relationship.started_at, relationship.ended_at,
                    relationship.mentorship_channel_id, relationship.starter_quests_removed)
                return True
        except Exception as e:
            logger.error(f"❌ Error saving mentorship relationship: {e}")
            return False

    async def get_mentorship_relationship(self, mentor_id: int, disciple_id: int, guild_id: int) -> Optional['MentorshipRelationship']:
        """Get mentorship relationship"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT * FROM mentorship_relationships 
                    WHERE mentor_id = $1 AND disciple_id = $2 AND guild_id = $3
                ''', mentor_id, disciple_id, guild_id)
                if row:
                    return MentorshipRelationship(
                        mentor_id=row['mentor_id'],
                        disciple_id=row['disciple_id'],
                        guild_id=row['guild_id'],
                        status=row['status'],
                        started_at=row['started_at'],
                        ended_at=row['ended_at'],
                        mentorship_channel_id=row['mentorship_channel_id'],
                        starter_quests_removed=row['starter_quests_removed']
                    )
                return None
        except Exception as e:
            logger.error(f"❌ Error getting mentorship relationship: {e}")
            return None

    async def get_disciple_mentor(self, disciple_id: int, guild_id: int) -> Optional['MentorshipRelationship']:
        """Get current mentor for a disciple"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT * FROM mentorship_relationships 
                    WHERE disciple_id = $1 AND guild_id = $2 AND status = 'active'
                ''', disciple_id, guild_id)
                if row:
                    return MentorshipRelationship(
                        mentor_id=row['mentor_id'],
                        disciple_id=row['disciple_id'],
                        guild_id=row['guild_id'],
                        status=row['status'],
                        started_at=row['started_at'],
                        ended_at=row['ended_at'],
                        mentorship_channel_id=row['mentorship_channel_id'],
                        starter_quests_removed=row['starter_quests_removed']
                    )
                return None
        except Exception as e:
            logger.error(f"❌ Error getting disciple mentor: {e}")
            return None

    async def remove_starter_quests_for_user(self, user_id: int, guild_id: int) -> bool:
        """Remove starter quests for a user who chose a mentor"""
        try:
            if not self.pool:
                raise RuntimeError("Database pool not initialized")
            async with self.pool.acquire() as conn:
                # Delete any starter quest progress for this user
                await conn.execute('''
                    DELETE FROM quest_progress 
                    WHERE user_id = $1 AND guild_id = $2 
                    AND quest_id LIKE 'starter%'
                ''', user_id, guild_id)
                return True
        except Exception as e:
            logger.error(f"❌ Error removing starter quests: {e}")
            return False