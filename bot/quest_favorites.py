import logging
from typing import List, Dict, Optional
from datetime import datetime
import discord
from bot.models import Quest, QuestRank, QuestCategory, QuestStatus

logger = logging.getLogger(__name__)

class QuestFavoritesSystem:
    """System for users to bookmark and manage favorite quests"""
    
    def __init__(self, database, quest_manager):
        self.database = database
        self.quest_manager = quest_manager
    
    async def initialize_favorites_system(self):
        """Initialize quest favorites system"""
        try:
            async with self.database.pool.acquire() as conn:
                # Quest favorites table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_favorites (
                        id SERIAL PRIMARY KEY,
                        quest_id VARCHAR(50) NOT NULL,
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        favorited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        notes TEXT,
                        UNIQUE (quest_id, user_id, guild_id)
                    )
                ''')
                
                # Favorite lists (collections of quests)
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_favorite_lists (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        list_name VARCHAR(100) NOT NULL,
                        description TEXT,
                        is_public BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (user_id, guild_id, list_name)
                    )
                ''')
                
                # Quest to list mappings
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_list_items (
                        list_id INTEGER REFERENCES quest_favorite_lists(id) ON DELETE CASCADE,
                        quest_id VARCHAR(50) NOT NULL,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (list_id, quest_id)
                    )
                ''')
                
            logger.info("✅ Quest favorites system initialized")
            
        except Exception as e:
            logger.error(f"❌ Error initializing quest favorites: {e}")
    
    async def add_favorite(self, quest_id: str, user_id: int, guild_id: int, notes: str = "") -> bool:
        """Add quest to user's favorites"""
        try:
            # Verify quest exists
            quest = await self.quest_manager.get_quest(quest_id)
            if not quest:
                return False
                
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_favorites (quest_id, user_id, guild_id, notes)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (quest_id, user_id, guild_id) DO NOTHING
                ''', quest_id, user_id, guild_id, notes)
                
                logger.info(f"⭐ {user_id} favorited quest {quest_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error adding favorite quest: {e}")
            return False
    
    async def remove_favorite(self, quest_id: str, user_id: int, guild_id: int) -> bool:
        """Remove quest from user's favorites"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.execute('''
                    DELETE FROM quest_favorites 
                    WHERE quest_id = $1 AND user_id = $2 AND guild_id = $3
                ''', quest_id, user_id, guild_id)
                
                logger.info(f"💔 {user_id} unfavorited quest {quest_id}")
                return result == "DELETE 1"
                
        except Exception as e:
            logger.error(f"❌ Error removing favorite quest: {e}")
            return False
    
    async def get_user_favorites(self, user_id: int, guild_id: int, include_unavailable: bool = False) -> List[Dict]:
        """Get user's favorite quests with details"""
        try:
            async with self.database.pool.acquire() as conn:
                status_filter = "" if include_unavailable else "AND q.status = 'available'"
                
                favorites = await conn.fetch(f'''
                    SELECT qf.*, q.title, q.description, q.rank, q.category, q.status, 
                           q.reward, q.creator_id, q.created_at as quest_created_at
                    FROM quest_favorites qf
                    JOIN quests q ON qf.quest_id = q.quest_id AND qf.guild_id = q.guild_id
                    WHERE qf.user_id = $1 AND qf.guild_id = $2 {status_filter}
                    ORDER BY qf.favorited_at DESC
                ''', user_id, guild_id)
                
                results = []
                for row in favorites:
                    quest_data = {
                        'favorite_id': row['id'],
                        'quest_id': row['quest_id'],
                        'title': row['title'],
                        'description': row['description'],
                        'rank': row['rank'],
                        'category': row['category'],
                        'status': row['status'],
                        'reward': row['reward'],
                        'creator_id': row['creator_id'],
                        'favorited_at': row['favorited_at'],
                        'notes': row['notes'],
                        'quest_created_at': row['quest_created_at']
                    }
                    results.append(quest_data)
                
                return results
                
        except Exception as e:
            logger.error(f"❌ Error getting user favorites: {e}")
            return []
    
    async def is_favorited(self, quest_id: str, user_id: int, guild_id: int) -> bool:
        """Check if quest is in user's favorites"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchval('''
                    SELECT EXISTS(
                        SELECT 1 FROM quest_favorites 
                        WHERE quest_id = $1 AND user_id = $2 AND guild_id = $3
                    )
                ''', quest_id, user_id, guild_id)
                
                return bool(result)
                
        except Exception as e:
            logger.error(f"❌ Error checking if quest is favorited: {e}")
            return False
    
    async def get_favorite_stats(self, user_id: int, guild_id: int) -> Dict:
        """Get user's favorite quest statistics"""
        try:
            async with self.database.pool.acquire() as conn:
                stats = await conn.fetchrow('''
                    SELECT 
                        COUNT(*) as total_favorites,
                        COUNT(CASE WHEN q.status = 'available' THEN 1 END) as available_favorites,
                        COUNT(CASE WHEN qp.status = 'approved' THEN 1 END) as completed_favorites
                    FROM quest_favorites qf
                    JOIN quests q ON qf.quest_id = q.quest_id AND qf.guild_id = q.guild_id
                    LEFT JOIN quest_progress qp ON q.quest_id = qp.quest_id AND qp.user_id = qf.user_id AND qp.status = 'approved'
                    WHERE qf.user_id = $1 AND qf.guild_id = $2
                ''', user_id, guild_id)
                
                # Get category breakdown
                categories = await conn.fetch('''
                    SELECT q.category, COUNT(*) as count
                    FROM quest_favorites qf
                    JOIN quests q ON qf.quest_id = q.quest_id AND qf.guild_id = q.guild_id
                    WHERE qf.user_id = $1 AND qf.guild_id = $2
                    GROUP BY q.category
                    ORDER BY count DESC
                ''', user_id, guild_id)
                
                return {
                    'total_favorites': stats['total_favorites'] or 0,
                    'available_favorites': stats['available_favorites'] or 0,
                    'completed_favorites': stats['completed_favorites'] or 0,
                    'category_breakdown': {row['category']: row['count'] for row in categories}
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting favorite stats: {e}")
            return {}
    
    async def create_favorite_list(self, user_id: int, guild_id: int, list_name: str, 
                                  description: str = "", is_public: bool = False) -> Optional[int]:
        """Create a new favorite list"""
        try:
            async with self.database.pool.acquire() as conn:
                list_id = await conn.fetchval('''
                    INSERT INTO quest_favorite_lists (user_id, guild_id, list_name, description, is_public)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                ''', user_id, guild_id, list_name, description, is_public)
                
                logger.info(f"📝 Created favorite list '{list_name}' for user {user_id}")
                return list_id
                
        except Exception as e:
            logger.error(f"❌ Error creating favorite list: {e}")
            return None
    
    async def add_to_list(self, list_id: int, quest_id: str) -> bool:
        """Add quest to a favorite list"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_list_items (list_id, quest_id)
                    VALUES ($1, $2)
                    ON CONFLICT (list_id, quest_id) DO NOTHING
                ''', list_id, quest_id)
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error adding quest to list: {e}")
            return False
    
    async def get_user_lists(self, user_id: int, guild_id: int) -> List[Dict]:
        """Get user's favorite lists"""
        try:
            async with self.database.pool.acquire() as conn:
                lists = await conn.fetch('''
                    SELECT l.*, COUNT(li.quest_id) as quest_count
                    FROM quest_favorite_lists l
                    LEFT JOIN quest_list_items li ON l.id = li.list_id
                    WHERE l.user_id = $1 AND l.guild_id = $2
                    GROUP BY l.id, l.user_id, l.guild_id, l.list_name, l.description, l.is_public, l.created_at
                    ORDER BY l.created_at DESC
                ''', user_id, guild_id)
                
                return [dict(row) for row in lists]
                
        except Exception as e:
            logger.error(f"❌ Error getting user lists: {e}")
            return []
    
    async def check_availability_changes(self, guild_id: int) -> List[Dict]:
        """Check for favorited quests that became available"""
        try:
            async with self.database.pool.acquire() as conn:
                # Find quests that were favorited when unavailable but are now available
                available_favorites = await conn.fetch('''
                    SELECT DISTINCT qf.user_id, qf.quest_id, q.title, qf.favorited_at
                    FROM quest_favorites qf
                    JOIN quests q ON qf.quest_id = q.quest_id AND qf.guild_id = q.guild_id
                    WHERE qf.guild_id = $1 AND q.status = 'available'
                    AND NOT EXISTS (
                        SELECT 1 FROM quest_progress qp 
                        WHERE qp.quest_id = qf.quest_id AND qp.user_id = qf.user_id 
                        AND qp.status IN ('accepted', 'completed', 'approved')
                    )
                ''', guild_id)
                
                return [dict(row) for row in available_favorites]
                
        except Exception as e:
            logger.error(f"❌ Error checking availability changes: {e}")
            return []
    
    def create_favorites_embed(self, favorites: List[Dict], user_name: str, page: int = 1, per_page: int = 5) -> discord.Embed:
        """Create embed for user's favorite quests"""
        if not favorites:
            embed = discord.Embed(
                title=f"⭐ {user_name}'s Favorite Quests",
                description="No favorite quests yet. Use the ⭐ button on quests you're interested in!",
                color=discord.Color.orange()
            )
            return embed
        
        total_pages = (len(favorites) + per_page - 1) // per_page
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_favorites = favorites[start_idx:end_idx]
        
        embed = discord.Embed(
            title=f"⭐ {user_name}'s Favorite Quests (Page {page}/{total_pages})",
            description=f"Your {len(favorites)} favorited quests:",
            color=discord.Color.gold()
        )
        
        for fav in page_favorites:
            # Status indicator
            if fav['status'] == QuestStatus.AVAILABLE:
                status_emoji = "🟢"
                status_text = "Available"
            else:
                status_emoji = "🔴"
                status_text = fav['status'].title()
            
            # Rank emoji
            rank_emojis = {
                QuestRank.EASY: "🟢",
                QuestRank.NORMAL: "🔵",
                QuestRank.MEDIUM: "🟠",
                QuestRank.HARD: "🔴", 
                QuestRank.IMPOSSIBLE: "🟣"
            }
            rank_emoji = rank_emojis.get(fav['rank'], "⚪")
            
            value_parts = [
                f"{rank_emoji} **{fav['rank'].title()}** • **{fav['category'].title()}** {status_emoji} {status_text}",
                f"{fav['description'][:100]}{'...' if len(fav['description']) > 100 else ''}"
            ]
            
            if fav['notes']:
                value_parts.append(f"*Note: {fav['notes'][:50]}{'...' if len(fav['notes']) > 50 else ''}*")
            
            value_parts.append(f"*Favorited {fav['favorited_at'].strftime('%m/%d/%y')} • Creator: <@{fav['creator_id']}>*")
            
            embed.add_field(
                name=f"⭐ {fav['title']} ({fav['quest_id']})",
                value="\n".join(value_parts),
                inline=False
            )
        
        embed.set_footer(text="Use /accept_quest <quest_id> to accept available quests • /unfavorite <quest_id> to remove")
        return embed
    
    def create_availability_notification_embed(self, available_quests: List[Dict]) -> discord.Embed:
        """Create notification embed for newly available favorited quests"""
        embed = discord.Embed(
            title="⭐ Favorited Quests Now Available!",
            description=f"{len(available_quests)} of your favorited quests are now available to accept:",
            color=discord.Color.green()
        )
        
        for quest in available_quests[:5]:  # Limit to 5 to avoid embed limits
            embed.add_field(
                name=f"⭐ {quest['title']}",
                value=f"Quest ID: `{quest['quest_id']}`\nFavorited: {quest['favorited_at'].strftime('%m/%d/%y')}",
                inline=True
            )
        
        if len(available_quests) > 5:
            embed.add_field(
                name="And more...",
                value=f"+{len(available_quests) - 5} additional quests available",
                inline=True
            )
        
        embed.set_footer(text="Use /my_favorites to see all your favorited quests")
        return embed