from typing import Optional, List, Dict
from datetime import datetime
from bot.sql_database import SQLDatabase
from bot.models import UserStats


class UserStatsManager:
    """Manages user statistics"""
    
    def __init__(self, database: SQLDatabase):
        self.database = database
    
    async def get_user_stats(self, user_id: int, guild_id: int) -> UserStats:
        """Get user statistics, create if doesn't exist"""
        stats = await self.database.get_user_stats(user_id, guild_id)
        if not stats:
            stats = UserStats(
                user_id=user_id,
                guild_id=guild_id,
                quests_completed=0,
                quests_accepted=0,
                quests_rejected=0,
                last_updated=datetime.now()
            )
            await self.database.save_user_stats(stats)
        return stats
    
    async def update_quest_accepted(self, user_id: int, guild_id: int):
        """Update stats when user accepts a quest"""
        stats = await self.get_user_stats(user_id, guild_id)
        stats.quests_accepted += 1
        stats.last_updated = datetime.now()
        await self.database.save_user_stats(stats)
    
    async def update_quest_completed(self, user_id: int, guild_id: int):
        """Update stats when user completes a quest"""
        stats = await self.get_user_stats(user_id, guild_id)
        stats.quests_completed += 1
        stats.last_updated = datetime.now()
        await self.database.save_user_stats(stats)
    
    async def update_quest_rejected(self, user_id: int, guild_id: int):
        """Update stats when user's quest is rejected"""
        stats = await self.get_user_stats(user_id, guild_id)
        stats.quests_rejected += 1
        stats.last_updated = datetime.now()
        await self.database.save_user_stats(stats)
    
    async def get_guild_leaderboard(self, guild_id: int, limit: int = 10) -> List[UserStats]:
        """Get guild leaderboard"""
        return await self.database.get_guild_leaderboard(guild_id, limit)
    
    async def get_total_guild_stats(self, guild_id: int) -> Dict[str, int]:
        """Get total guild statistics"""
        return await self.database.get_total_guild_stats(guild_id)