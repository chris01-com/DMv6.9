import asyncio
import logging
from typing import List

logger = logging.getLogger(__name__)

class DatabaseOptimizer:
    """Database optimization and indexing manager"""
    
    def __init__(self, database):
        self.database = database
    
    async def create_performance_indexes(self):
        """Create database indexes for better performance"""
        
        # Check which tables exist first
        existing_tables = await self._get_existing_tables()
        
        indexes = []
        
        # Leaderboard indexes (always exists)
        indexes.extend([
            "CREATE INDEX IF NOT EXISTS idx_leaderboard_guild_points ON leaderboard(guild_id, points DESC)",
            "CREATE INDEX IF NOT EXISTS idx_leaderboard_user_guild ON leaderboard(user_id, guild_id)"
        ])
        
        # Quest indexes (always exists)
        indexes.extend([
            "CREATE INDEX IF NOT EXISTS idx_quests_creator ON quests(creator_id, guild_id)",
            "CREATE INDEX IF NOT EXISTS idx_quests_rank_category ON quests(rank, category)"
        ])
        
        # Quest progress indexes (always exists)
        indexes.extend([
            "CREATE INDEX IF NOT EXISTS idx_quest_progress_quest_user ON quest_progress(quest_id, user_id)"
        ])
        
        # User stats indexes (always exists)
        if 'user_stats' in existing_tables:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_user_stats_guild_user ON user_stats(guild_id, user_id)")
        
        # Mentor system indexes
        if 'mentors' in existing_tables:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_mentors_guild_active ON mentors(guild_id, is_active)")
        
        if 'welcome_automation' in existing_tables:
            indexes.extend([
                "CREATE INDEX IF NOT EXISTS idx_welcome_automation_user ON welcome_automation(user_id, guild_id)"
            ])
        
        # Team quest indexes (only if tables exist)
        if 'team_quests' in existing_tables:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_team_quests_guild ON team_quests(guild_id)")
        
        if 'team_quest_members' in existing_tables:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_team_quest_members_team ON team_quest_members(team_quest_id)")
        
        # Bounty indexes (only if table exists)
        if 'bounties' in existing_tables:
            indexes.extend([
                "CREATE INDEX IF NOT EXISTS idx_bounties_guild ON bounties(guild_id)",
                "CREATE INDEX IF NOT EXISTS idx_bounties_creator ON bounties(creator_id, guild_id)"
            ])
        
        # Mentor quest indexes (only if table exists)
        if 'mentor_quests' in existing_tables:
            indexes.append("CREATE INDEX IF NOT EXISTS idx_mentor_quests_mentor_student ON mentor_quests(mentor_id, student_id)")
        
        try:
            async with self.database.pool.acquire() as conn:
                for index_sql in indexes:
                    try:
                        await conn.execute(index_sql)
                        index_name = index_sql.split('idx_')[1].split(' ')[0] if 'idx_' in index_sql else 'unknown'
                        logger.info(f"✅ Created index: {index_name}")
                    except Exception as e:
                        # Only log if it's not a "already exists" error or startup timing issue
                        if "already exists" not in str(e).lower():
                            if "does not exist" in str(e):
                                logger.debug(f"Index creation skipped (table not ready): {e}")
                            else:
                                logger.warning(f"⚠️ Index creation failed: {e}")
                        
            logger.info("✅ Database optimization complete")
            
        except Exception as e:
            logger.error(f"❌ Error creating performance indexes: {e}")
    
    async def _get_existing_tables(self) -> set:
        """Get list of existing tables in the database"""
        try:
            async with self.database.pool.acquire() as conn:
                tables = await conn.fetch('''
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public'
                ''')
                return {row['table_name'] for row in tables}
        except Exception as e:
            logger.error(f"❌ Error getting existing tables: {e}")
            return set()
    
    async def analyze_table_statistics(self):
        """Analyze table statistics for query optimization"""
        try:
            async with self.database.pool.acquire() as conn:
                # Update table statistics for better query planning
                tables = [
                    'leaderboard', 'quests', 'quest_progress', 'user_stats',
                    'mentors', 'welcome_automation', 'team_quests', 'bounties'
                ]
                
                for table in tables:
                    try:
                        await conn.execute(f"ANALYZE {table}")
                        logger.debug(f"✅ Analyzed table: {table}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to analyze table {table}: {e}")
                        
        except Exception as e:
            logger.error(f"❌ Error analyzing table statistics: {e}")
    
    async def vacuum_database(self):
        """Perform database maintenance"""
        try:
            async with self.database.pool.acquire() as conn:
                # Note: VACUUM cannot be run inside a transaction block
                # So we'll use VACUUM (ANALYZE) which can be run in transaction
                await conn.execute("VACUUM ANALYZE")
                logger.info("✅ Database vacuum complete")
                
        except Exception as e:
            logger.error(f"❌ Error during database vacuum: {e}")
    
    async def get_table_sizes(self) -> dict:
        """Get size information for all tables"""
        try:
            async with self.database.pool.acquire() as conn:
                sizes = await conn.fetch('''
                    SELECT 
                        schemaname,
                        tablename,
                        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                        pg_total_relation_size(schemaname||'.'||tablename) AS size_bytes
                    FROM pg_tables 
                    WHERE schemaname = 'public'
                    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                ''')
                
                return {row['tablename']: row['size'] for row in sizes}
                
        except Exception as e:
            logger.error(f"❌ Error getting table sizes: {e}")
            return {}
    
    async def optimize_quest_queries(self):
        """Create specialized indexes for quest-related queries"""
        quest_indexes = [
            # Compound index for quest browsing
            "CREATE INDEX IF NOT EXISTS idx_quests_browse ON quests(guild_id, status, rank, category) WHERE status = 'available'",
            
            # Index for user quest progress tracking  
            "CREATE INDEX IF NOT EXISTS idx_progress_tracking ON quest_progress(user_id, guild_id, status, completed_at)",
            
            # Index for leaderboard ranking
            "CREATE INDEX IF NOT EXISTS idx_leaderboard_ranking ON leaderboard(guild_id, points DESC, username)",
            
            # Index for mentor performance queries
            "CREATE INDEX IF NOT EXISTS idx_mentor_performance ON welcome_automation(mentor_id, guild_id, quest_1_completed, quest_2_completed)"
        ]
        
        try:
            async with self.database.pool.acquire() as conn:
                for index_sql in quest_indexes:
                    try:
                        await conn.execute(index_sql)
                    except Exception as e:
                        # Don't log errors for expected timing issues during startup
                        if "does not exist" in str(e):
                            logger.debug(f"Index creation skipped (table not ready): {e}")
                        else:
                            logger.debug(f"Quest index already exists or failed: {e}")
                        
            logger.info("✅ Quest query optimization complete")
            
        except Exception as e:
            logger.error(f"❌ Error optimizing quest queries: {e}")