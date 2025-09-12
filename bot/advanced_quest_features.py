import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from bot.models import Quest, QuestRank

logger = logging.getLogger(__name__)

class AdvancedQuestFeatures:
    """Advanced quest features including chains, dependencies, and scaling"""
    
    def __init__(self, database, quest_manager):
        self.database = database
        self.quest_manager = quest_manager
    
    async def initialize_quest_features(self):
        """Initialize advanced quest feature tables"""
        try:
            async with self.database.pool.acquire() as conn:
                # Quest chains table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_chains (
                        chain_id VARCHAR(50) PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        creator_id BIGINT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Quest dependencies table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_dependencies (
                        quest_id VARCHAR(50) NOT NULL,
                        prerequisite_quest_id VARCHAR(50) NOT NULL,
                        guild_id BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (quest_id, prerequisite_quest_id)
                    )
                ''')
                
                # Quest scaling table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_scaling (
                        quest_id VARCHAR(50) PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        base_reward INTEGER DEFAULT 0,
                        scaling_factor DECIMAL(3,2) DEFAULT 1.0,
                        max_attempts INTEGER DEFAULT 0,
                        current_attempts INTEGER DEFAULT 0,
                        last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Quest categories with special rewards
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_categories (
                        category_name VARCHAR(100) NOT NULL,
                        guild_id BIGINT NOT NULL,
                        bonus_multiplier DECIMAL(3,2) DEFAULT 1.0,
                        special_role_id BIGINT,
                        completion_threshold INTEGER DEFAULT 10,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (category_name, guild_id)
                    )
                ''')
                
                logger.info("✅ Advanced quest features tables initialized")
                
        except Exception as e:
            logger.error(f"❌ Error initializing quest features: {e}")
    
    async def create_quest_chain(self, guild_id: int, creator_id: int, name: str, 
                                description: str, quest_ids: List[str]) -> Optional[str]:
        """Create a new quest chain"""
        try:
            import uuid
            chain_id = str(uuid.uuid4())[:8]
            
            async with self.database.pool.acquire() as conn:
                # Create the chain
                await conn.execute('''
                    INSERT INTO quest_chains (chain_id, guild_id, name, description, creator_id)
                    VALUES ($1, $2, $3, $4, $5)
                ''', chain_id, guild_id, name, description, creator_id)
                
                # Set up dependencies between quests in the chain
                for i in range(1, len(quest_ids)):
                    await conn.execute('''
                        INSERT INTO quest_dependencies (quest_id, prerequisite_quest_id, guild_id)
                        VALUES ($1, $2, $3)
                        ON CONFLICT DO NOTHING
                    ''', quest_ids[i], quest_ids[i-1], guild_id)
                
                logger.info(f"✅ Created quest chain {name} with {len(quest_ids)} quests")
                return chain_id
                
        except Exception as e:
            logger.error(f"❌ Error creating quest chain: {e}")
            return None
    
    async def check_quest_prerequisites(self, user_id: int, quest_id: str, guild_id: int) -> bool:
        """Check if user has completed all prerequisite quests"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get all prerequisites for this quest
                prerequisites = await conn.fetch('''
                    SELECT prerequisite_quest_id FROM quest_dependencies 
                    WHERE quest_id = $1 AND guild_id = $2
                ''', quest_id, guild_id)
                
                if not prerequisites:
                    return True  # No prerequisites
                
                # Check if user has completed all prerequisites
                for prereq in prerequisites:
                    completed = await conn.fetchval('''
                        SELECT COUNT(*) FROM quest_progress 
                        WHERE user_id = $1 AND quest_id = $2 AND status = 'approved'
                    ''', user_id, prereq['prerequisite_quest_id'])
                    
                    if not completed:
                        return False
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error checking quest prerequisites: {e}")
            return False
    
    async def get_missing_prerequisites(self, user_id: int, quest_id: str, guild_id: int) -> List[str]:
        """Get list of missing prerequisite quests"""
        try:
            async with self.database.pool.acquire() as conn:
                missing = await conn.fetch('''
                    SELECT qd.prerequisite_quest_id, q.title
                    FROM quest_dependencies qd
                    JOIN quests q ON qd.prerequisite_quest_id = q.quest_id
                    WHERE qd.quest_id = $1 AND qd.guild_id = $2
                    AND NOT EXISTS (
                        SELECT 1 FROM quest_progress qp 
                        WHERE qp.user_id = $3 AND qp.quest_id = qd.prerequisite_quest_id 
                        AND qp.status = 'approved'
                    )
                ''', quest_id, guild_id, user_id)
                
                return [f"{row['title']} ({row['prerequisite_quest_id']})" for row in missing]
                
        except Exception as e:
            logger.error(f"❌ Error getting missing prerequisites: {e}")
            return []
    
    async def calculate_scaled_reward(self, quest_id: str, guild_id: int) -> int:
        """Calculate reward - now returns base reward without scaling"""
        try:
            async with self.database.pool.acquire() as conn:
                scaling_info = await conn.fetchrow('''
                    SELECT base_reward FROM quest_scaling 
                    WHERE quest_id = $1 AND guild_id = $2
                ''', quest_id, guild_id)
                
                if not scaling_info:
                    return 0
                
                # Return base reward without any scaling/decrease
                base_reward = scaling_info['base_reward']
                return base_reward if base_reward > 0 else 0
                
        except Exception as e:
            logger.error(f"❌ Error calculating reward: {e}")
            return 0
    
    async def update_quest_attempts(self, quest_id: str, guild_id: int):
        """Update quest attempt count (tracking only, no scaling applied)"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE quest_scaling 
                    SET current_attempts = current_attempts + 1
                    WHERE quest_id = $1 AND guild_id = $2
                ''', quest_id, guild_id)
                
        except Exception as e:
            logger.error(f"❌ Error updating quest attempts: {e}")
    
    async def setup_category_rewards(self, guild_id: int, category: str, 
                                   bonus_multiplier: float, special_role_id: Optional[int] = None,
                                   completion_threshold: int = 10):
        """Set up special rewards for quest categories"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_categories 
                    (category_name, guild_id, bonus_multiplier, special_role_id, completion_threshold)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (category_name, guild_id) DO UPDATE SET
                        bonus_multiplier = EXCLUDED.bonus_multiplier,
                        special_role_id = EXCLUDED.special_role_id,
                        completion_threshold = EXCLUDED.completion_threshold
                ''', category, guild_id, bonus_multiplier, special_role_id, completion_threshold)
                
                logger.info(f"✅ Set up category rewards for {category}")
                
        except Exception as e:
            logger.error(f"❌ Error setting up category rewards: {e}")
    
    async def check_category_completion(self, user_id: int, guild_id: int, category: str) -> bool:
        """Check if user has reached category completion threshold"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get category threshold
                threshold_info = await conn.fetchrow('''
                    SELECT completion_threshold, special_role_id 
                    FROM quest_categories 
                    WHERE category_name = $1 AND guild_id = $2
                ''', category, guild_id)
                
                if not threshold_info:
                    return False
                
                # Count user's completed quests in this category
                completed_count = await conn.fetchval('''
                    SELECT COUNT(*) FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 
                    AND q.category = $3 AND qp.status = 'approved'
                ''', user_id, guild_id, category)
                
                return completed_count >= threshold_info['completion_threshold']
                
        except Exception as e:
            logger.error(f"❌ Error checking category completion: {e}")
            return False
    
    async def get_quest_chain_progress(self, user_id: int, chain_id: str, guild_id: int) -> Dict:
        """Get user's progress through a quest chain"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get chain info
                chain_info = await conn.fetchrow('''
                    SELECT name, description FROM quest_chains 
                    WHERE chain_id = $1 AND guild_id = $2
                ''', chain_id, guild_id)
                
                if not chain_info:
                    return {}
                
                # Get all quests in the chain (through dependencies)
                chain_quests = await conn.fetch('''
                    SELECT DISTINCT q.quest_id, q.title, q.rank,
                           CASE WHEN qp.status = 'approved' THEN TRUE ELSE FALSE END as completed
                    FROM quest_dependencies qd
                    JOIN quests q ON (qd.quest_id = q.quest_id OR qd.prerequisite_quest_id = q.quest_id)
                    LEFT JOIN quest_progress qp ON q.quest_id = qp.quest_id AND qp.user_id = $1
                    WHERE qd.guild_id = $2
                    ORDER BY q.quest_id
                ''', user_id, guild_id)
                
                completed_count = sum(1 for q in chain_quests if q['completed'])
                total_count = len(chain_quests)
                
                return {
                    'chain_name': chain_info['name'],
                    'description': chain_info['description'],
                    'completed': completed_count,
                    'total': total_count,
                    'progress_percent': (completed_count / total_count * 100) if total_count > 0 else 0,
                    'quests': [{
                        'quest_id': q['quest_id'],
                        'title': q['title'],
                        'rank': q['rank'],
                        'completed': q['completed']
                    } for q in chain_quests]
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting quest chain progress: {e}")
            return {}