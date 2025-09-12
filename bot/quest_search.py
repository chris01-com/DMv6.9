import logging
from typing import List, Dict, Optional, Tuple
import re
import discord
from bot.models import Quest, QuestRank, QuestCategory, QuestStatus

logger = logging.getLogger(__name__)

class QuestSearchSystem:
    """Advanced quest search functionality with multiple search criteria"""
    
    def __init__(self, database, quest_manager):
        self.database = database
        self.quest_manager = quest_manager
    
    async def search_quests(self, guild_id: int, **search_params) -> List[Quest]:
        """
        Search quests with multiple criteria
        
        Parameters:
        - query: Text search in title, description, requirements, rewards
        - creator_id: Filter by quest creator
        - rank: Filter by quest difficulty rank
        - category: Filter by quest category
        - min_reward: Minimum reward points
        - max_reward: Maximum reward points
        - reward_contains: Text that must be in reward description
        - status: Quest status filter
        - has_role_requirements: Filter quests that require specific roles
        - user_id: For checking user eligibility (optional)
        """
        
        query = search_params.get('query', '').strip()
        creator_id = search_params.get('creator_id')
        rank = search_params.get('rank')
        category = search_params.get('category')
        min_reward = search_params.get('min_reward')
        max_reward = search_params.get('max_reward')
        reward_contains = search_params.get('reward_contains', '').strip()
        status = search_params.get('status', QuestStatus.AVAILABLE)
        has_role_requirements = search_params.get('has_role_requirements')
        user_id = search_params.get('user_id')
        
        try:
            # Build dynamic query
            base_query = '''
                SELECT DISTINCT q.* FROM quests q
                WHERE q.guild_id = $1
            '''
            params = [guild_id]
            param_count = 1
            
            # Add status filter
            if status:
                param_count += 1
                base_query += f" AND q.status = ${param_count}"
                params.append(status)
            
            # Add text search
            if query:
                param_count += 1
                base_query += f" AND (LOWER(q.title) LIKE ${param_count} OR LOWER(q.description) LIKE ${param_count} OR LOWER(q.requirements) LIKE ${param_count} OR LOWER(q.reward) LIKE ${param_count})"
                search_term = f"%{query.lower()}%"
                params.append(search_term)
            
            # Add creator filter
            if creator_id:
                param_count += 1
                base_query += f" AND q.creator_id = ${param_count}"
                params.append(creator_id)
            
            # Add rank filter
            if rank:
                param_count += 1
                base_query += f" AND q.rank = ${param_count}"
                params.append(rank)
            
            # Add category filter
            if category:
                param_count += 1
                base_query += f" AND q.category = ${param_count}"
                params.append(category)
            
            # Add reward text filter
            if reward_contains:
                param_count += 1
                base_query += f" AND LOWER(q.reward) LIKE ${param_count}"
                params.append(f"%{reward_contains.lower()}%")
            
            # Add role requirements filter
            if has_role_requirements is not None:
                if has_role_requirements:
                    base_query += " AND q.required_role_ids IS NOT NULL AND array_length(q.required_role_ids, 1) > 0"
                else:
                    base_query += " AND (q.required_role_ids IS NULL OR array_length(q.required_role_ids, 1) = 0)"
            
            # Add reward points filtering (extract from reward text)
            if min_reward is not None or max_reward is not None:
                base_query += " AND ("
                reward_conditions = []
                
                if min_reward is not None:
                    # Look for number patterns in reward text
                    reward_conditions.append(f"(q.reward ~ '\\d+' AND CAST(substring(q.reward from '\\d+') AS INTEGER) >= {min_reward})")
                
                if max_reward is not None:
                    reward_conditions.append(f"(q.reward ~ '\\d+' AND CAST(substring(q.reward from '\\d+') AS INTEGER) <= {max_reward})")
                
                base_query += " OR ".join(reward_conditions) + ")"
            
            # Add user eligibility check if user_id provided
            if user_id:
                base_query += '''
                    AND q.quest_id NOT IN (
                        SELECT quest_id FROM quest_progress 
                        WHERE user_id = $''' + str(param_count + 1) + ''' 
                        AND status IN ('accepted', 'completed')
                    )
                '''
                params.append(user_id)
            
            # Add ordering
            base_query += " ORDER BY q.created_at DESC"
            
            # Execute query
            async with self.database.pool.acquire() as conn:
                quest_rows = await conn.fetch(base_query, *params)
                
                # Convert to Quest objects
                quests = []
                for row in quest_rows:
                    quest = Quest(
                        quest_id=row['quest_id'],
                        title=row['title'],
                        description=row['description'],
                        creator_id=row['creator_id'],
                        guild_id=row['guild_id'],
                        requirements=row['requirements'] or "",
                        reward=row['reward'] or "",
                        rank=row['rank'] or QuestRank.NORMAL,
                        category=row['category'] or QuestCategory.OTHER,
                        status=row['status'] or QuestStatus.AVAILABLE,
                        created_at=row['created_at'],
                        required_role_ids=row.get('required_role_ids', []) or []
                    )
                    quests.append(quest)
                
                return quests
                
        except Exception as e:
            logger.error(f"❌ Error searching quests: {e}")
            return []
    
    async def search_by_creator(self, guild_id: int, creator_id: int, include_completed: bool = False) -> List[Quest]:
        """Search quests created by specific user"""
        statuses = [QuestStatus.AVAILABLE]
        if include_completed:
            statuses.extend([QuestStatus.APPROVED, QuestStatus.COMPLETED, QuestStatus.REJECTED])
        
        try:
            async with self.database.pool.acquire() as conn:
                quest_rows = await conn.fetch('''
                    SELECT * FROM quests 
                    WHERE guild_id = $1 AND creator_id = $2 AND status = ANY($3)
                    ORDER BY created_at DESC
                ''', guild_id, creator_id, statuses)
                
                quests = []
                for row in quest_rows:
                    quest = Quest(
                        quest_id=row['quest_id'],
                        title=row['title'],
                        description=row['description'],
                        creator_id=row['creator_id'],
                        guild_id=row['guild_id'],
                        requirements=row['requirements'] or "",
                        reward=row['reward'] or "",
                        rank=row['rank'] or QuestRank.NORMAL,
                        category=row['category'] or QuestCategory.OTHER,
                        status=row['status'] or QuestStatus.AVAILABLE,
                        created_at=row['created_at'],
                        required_role_ids=row.get('required_role_ids', []) or []
                    )
                    quests.append(quest)
                
                return quests
                
        except Exception as e:
            logger.error(f"❌ Error searching quests by creator: {e}")
            return []
    
    async def get_popular_quests(self, guild_id: int, limit: int = 10) -> List[Tuple[Quest, int]]:
        """Get most accepted/completed quests"""
        try:
            async with self.database.pool.acquire() as conn:
                popular_quests = await conn.fetch('''
                    SELECT q.*, COUNT(qp.quest_id) as acceptance_count
                    FROM quests q
                    LEFT JOIN quest_progress qp ON q.quest_id = qp.quest_id
                    WHERE q.guild_id = $1
                    GROUP BY q.quest_id, q.title, q.description, q.creator_id, q.guild_id, 
                             q.requirements, q.reward, q.rank, q.category, q.status, 
                             q.created_at, q.required_role_ids
                    ORDER BY acceptance_count DESC, q.created_at DESC
                    LIMIT $2
                ''', guild_id, limit)
                
                results = []
                for row in popular_quests:
                    quest = Quest(
                        quest_id=row['quest_id'],
                        title=row['title'],
                        description=row['description'],
                        creator_id=row['creator_id'],
                        guild_id=row['guild_id'],
                        requirements=row['requirements'] or "",
                        reward=row['reward'] or "",
                        rank=row['rank'] or QuestRank.NORMAL,
                        category=row['category'] or QuestCategory.OTHER,
                        status=row['status'] or QuestStatus.AVAILABLE,
                        created_at=row['created_at'],
                        required_role_ids=row.get('required_role_ids', []) or []
                    )
                    results.append((quest, row['acceptance_count']))
                
                return results
                
        except Exception as e:
            logger.error(f"❌ Error getting popular quests: {e}")
            return []
    
    async def get_recent_quests(self, guild_id: int, days: int = 7, limit: int = 20) -> List[Quest]:
        """Get recently created quests"""
        try:
            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=days)
            
            async with self.database.pool.acquire() as conn:
                quest_rows = await conn.fetch('''
                    SELECT * FROM quests 
                    WHERE guild_id = $1 AND created_at >= $2 AND status = $3
                    ORDER BY created_at DESC
                    LIMIT $4
                ''', guild_id, cutoff_date, QuestStatus.AVAILABLE, limit)
                
                quests = []
                for row in quest_rows:
                    quest = Quest(
                        quest_id=row['quest_id'],
                        title=row['title'],
                        description=row['description'],
                        creator_id=row['creator_id'],
                        guild_id=row['guild_id'],
                        requirements=row['requirements'] or "",
                        reward=row['reward'] or "",
                        rank=row['rank'] or QuestRank.NORMAL,
                        category=row['category'] or QuestCategory.OTHER,
                        status=row['status'] or QuestStatus.AVAILABLE,
                        created_at=row['created_at'],
                        required_role_ids=row.get('required_role_ids', []) or []
                    )
                    quests.append(quest)
                
                return quests
                
        except Exception as e:
            logger.error(f"❌ Error getting recent quests: {e}")
            return []
    
    def extract_reward_points(self, reward_text: str) -> Optional[int]:
        """Extract numeric points from reward text"""
        if not reward_text:
            return None
            
        # Look for patterns like "50 points", "100pts", "25 coins", etc.
        patterns = [
            r'(\d+)\s*points?',
            r'(\d+)\s*pts?',
            r'(\d+)\s*coins?',
            r'(\d+)\s*gold',
            r'(\d+)\s*credits?'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, reward_text.lower())
            if match:
                return int(match.group(1))
        
        # Fallback: just look for any number
        number_match = re.search(r'(\d+)', reward_text)
        if number_match:
            return int(number_match.group(1))
            
        return None
    
    def create_search_embed(self, quests: List[Quest], search_params: Dict, page: int = 1, total_pages: int = 1) -> discord.Embed:
        """Create embed for search results"""
        if not quests:
            embed = discord.Embed(
                title="🔍 Quest Search Results",
                description="No quests found matching your criteria.",
                color=discord.Color.orange()
            )
            return embed
        
        # Build search criteria description
        criteria = []
        if search_params.get('query'):
            criteria.append(f"Text: '{search_params['query']}'")
        if search_params.get('rank'):
            criteria.append(f"Rank: {search_params['rank'].title()}")
        if search_params.get('category'):
            criteria.append(f"Category: {search_params['category'].title()}")
        if search_params.get('creator_id'):
            criteria.append(f"Creator: <@{search_params['creator_id']}>")
        if search_params.get('reward_contains'):
            criteria.append(f"Reward contains: '{search_params['reward_contains']}'")
        
        criteria_text = " • ".join(criteria) if criteria else "All available quests"
        
        embed = discord.Embed(
            title=f"🔍 Quest Search Results (Page {page}/{total_pages})",
            description=f"**Search criteria:** {criteria_text}\n**Found {len(quests)} quest(s)**",
            color=discord.Color.blue()
        )
        
        # Add quest results
        for i, quest in enumerate(quests, 1):
            rank_emoji = self._get_rank_emoji(quest.rank)
            category_emoji = self._get_category_emoji(quest.category)
            
            reward_points = self.extract_reward_points(quest.reward)
            reward_text = f" • {reward_points} pts" if reward_points else ""
            
            embed.add_field(
                name=f"{rank_emoji} {quest.title} ({quest.quest_id})",
                value=(
                    f"{category_emoji} **{quest.category.title()}** • **{quest.rank.title()}**{reward_text}\n"
                    f"{quest.description[:100]}{'...' if len(quest.description) > 100 else ''}\n"
                    f"*Creator: <@{quest.creator_id}>*"
                ),
                inline=False
            )
        
        embed.set_footer(text="Use /accept_quest <quest_id> to accept a quest")
        return embed
    
    def _get_rank_emoji(self, rank: str) -> str:
        """Get emoji for quest rank"""
        emojis = {
            QuestRank.EASY: "🟢",
            QuestRank.NORMAL: "🔵", 
            QuestRank.MEDIUM: "🟠",
            QuestRank.HARD: "🔴",
            QuestRank.IMPOSSIBLE: "🟣"
        }
        return emojis.get(rank, "⚪")
    
    def _get_category_emoji(self, category: str) -> str:
        """Get emoji for quest category"""
        emojis = {
            QuestCategory.HUNTING: "🏹",
            QuestCategory.GATHERING: "🌾",
            QuestCategory.COLLECTING: "📦",
            QuestCategory.CRAFTING: "🔨",
            QuestCategory.EXPLORATION: "🗺️",
            QuestCategory.COMBAT: "⚔️",
            QuestCategory.SOCIAL: "👥",
            QuestCategory.BUILDING: "🏗️",
            QuestCategory.TRADING: "💰",
            QuestCategory.PUZZLE: "🧩",
            QuestCategory.SURVIVAL: "🏕️",
            QuestCategory.TEAM: "🤝",
            QuestCategory.OTHER: "📋"
        }
        return emojis.get(category, "📋")