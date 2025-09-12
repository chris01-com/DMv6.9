from __future__ import annotations
import json
import os
import asyncio
from datetime import datetime
import logging
from urllib.parse import urlparse
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

try:
    import asyncpg
    from asyncpg import exceptions as asyncpg_exceptions
except ImportError:
    raise ImportError("asyncpg package is required")

if TYPE_CHECKING:
    try:
        from discord.ext import commands
        from bot.sql_database import SQLDatabase
    except ImportError:
        pass

logger = logging.getLogger(__name__)

class LeaderboardManager:
    """Enhanced leaderboard manager with improved error handling and logging"""

    def __init__(self, database: 'SQLDatabase'):
        self.database = database
        self.pool = database.pool if database else None
        self.bot: Optional['commands.Bot'] = None  # Will be set later by the bot instance
        self._mentor_cache: Dict = {}  # Cache for mentor status checks
        self._cache_timestamp: Dict = {}  # Track cache freshness
        self._cache_duration: int = 300  # 5 minutes cache duration

    async def initialize_db(self):
        """Initialize database connection with enhanced error handling"""
        if self.database:
            return await self.database.initialize()
        return False

    async def add_member(self, guild_id: int, user_id: int, display_name: str) -> bool:
        """Add a new member to the leaderboard"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return False
        try:
            async with self.database.pool.acquire() as conn:
                # Check if member already exists first
                existing = await conn.fetchrow('''
                    SELECT user_id FROM leaderboard 
                    WHERE guild_id = $1 AND user_id = $2
                ''', guild_id, user_id)

                if existing:
                    # Update existing member
                    await conn.execute('''
                        UPDATE leaderboard 
                        SET username = $3, display_name = $3, last_updated = CURRENT_TIMESTAMP
                        WHERE guild_id = $1 AND user_id = $2
                    ''', guild_id, user_id, display_name)
                else:
                    # Insert new member
                    await conn.execute('''
                        INSERT INTO leaderboard (guild_id, user_id, username, display_name, points, total_points_earned, created_at, last_updated)
                        VALUES ($1, $2, $3, $3, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ''', guild_id, user_id, display_name)

                logger.info(f"✅ Added member {display_name} to leaderboard for guild {guild_id}")
                return True

        except Exception as e:
            logger.error(f"❌ Error adding member {display_name}: {e}")
            return False

    async def remove_member(self, guild_id: int, user_id: int):
        """Remove a member from the leaderboard"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    DELETE FROM leaderboard WHERE guild_id = $1 AND user_id = $2
                ''', guild_id, user_id)
                await conn.execute('''
                    DELETE FROM user_stats WHERE guild_id = $1 AND user_id = $2
                ''', guild_id, user_id)
            logger.info(f"✅ Removed member {user_id} from guild {guild_id}")
        except asyncpg_exceptions.ConnectionDoesNotExistError as e:
            logger.error(f"❌ Database connection error removing member {user_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Error removing member {user_id}: {e}")

    async def update_points(self, guild_id: int, user_id: int, points_change: int, username: str) -> bool:
        """Update points for a user (can be positive or negative)"""
        return await self.database.update_points(guild_id, user_id, points_change, username)

    async def add_points(self, guild_id: int, user_id: int, points: int, username: str) -> bool:
        """Add points to a user (alias for update_points with positive value)"""
        return await self.update_points(guild_id, user_id, points, username)

    async def get_user_stats(self, guild_id: int, user_id: int) -> Optional[Dict]:
        """Get comprehensive user statistics"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return None
        try:
            async with self.database.pool.acquire() as conn:
                # Get leaderboard data with correct ranking
                leaderboard_row = await conn.fetchrow('''
                    SELECT user_data.*, ranking.rank
                    FROM (
                        SELECT *, 
                               ROW_NUMBER() OVER (PARTITION BY guild_id ORDER BY points DESC) as rank
                        FROM leaderboard 
                        WHERE guild_id = $1
                    ) ranking
                    JOIN leaderboard user_data ON ranking.user_id = user_data.user_id 
                                                AND ranking.guild_id = user_data.guild_id
                    WHERE ranking.user_id = $2 AND ranking.guild_id = $1
                ''', guild_id, user_id)

                if not leaderboard_row:
                    # Create default stats entry if user doesn't exist
                    await self.add_member(guild_id, user_id, f"User_{user_id}")
                    # Retry after creating the user with correct ranking
                    leaderboard_row = await conn.fetchrow('''
                        SELECT user_data.*, ranking.rank
                        FROM (
                            SELECT *, 
                                   ROW_NUMBER() OVER (PARTITION BY guild_id ORDER BY points DESC) as rank
                            FROM leaderboard 
                            WHERE guild_id = $1
                        ) ranking
                        JOIN leaderboard user_data ON ranking.user_id = user_data.user_id 
                                                    AND ranking.guild_id = user_data.guild_id
                        WHERE ranking.user_id = $2 AND ranking.guild_id = $1
                    ''', guild_id, user_id)

                    if not leaderboard_row:
                        return None

                # Get quest stats
                quest_stats_row = await conn.fetchrow('''
                    SELECT * FROM user_stats WHERE guild_id = $1 AND user_id = $2
                ''', guild_id, user_id)

                stats = {
                    'guild_id': guild_id,
                    'user_id': user_id,
                    'username': leaderboard_row['username'],
                    'points': leaderboard_row['points'],
                    'rank': leaderboard_row['rank'],
                    'last_updated': leaderboard_row['last_updated'],
                    'created_at': leaderboard_row['created_at']
                }

                # Add quest stats if available
                if quest_stats_row:
                    stats.update({
                        'quests_completed': quest_stats_row['quests_completed'],
                        'quests_accepted': quest_stats_row['quests_accepted'],
                        'quests_rejected': quest_stats_row['quests_rejected'],
                        'custom_title': quest_stats_row['custom_title'],
                        'status_message': quest_stats_row['status_message'],
                        'preferred_color': quest_stats_row['preferred_color'],
                        'notification_dm': quest_stats_row['notification_dm'],
                        'total_points_earned': quest_stats_row['total_points_earned'] if 'total_points_earned' in quest_stats_row else leaderboard_row['points']
                    })
                else:
                    # Default quest stats
                    stats.update({
                        'quests_completed': 0,
                        'quests_accepted': 0,
                        'quests_rejected': 0,
                        'custom_title': '',
                        'status_message': '',
                        'preferred_color': '#2C3E50',
                        'notification_dm': True,
                        'total_points_earned': leaderboard_row['points']  # Use leaderboard points as fallback
                    })

                return stats

        except asyncpg_exceptions.ConnectionDoesNotExistError as e:
            logger.error(f"❌ Database connection error getting user stats: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error getting user stats: {e}")
            return None

    async def _get_leaderboard_async(self, guild_id: int, page: int = 1, per_page: int = 50) -> Tuple[List[Dict], int, int]:
        """Get leaderboard data with pagination, filtering out users no longer in the server"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return [], 1, 1
        try:
            # Get guild instance to check member existence
            guild = None
            if self.bot:
                guild = self.bot.get_guild(guild_id)
            
            async with self.database.pool.acquire() as conn:
                # Get all leaderboard data first (we'll filter and paginate after)
                all_rows = await conn.fetch('''
                    SELECT *, 
                           ROW_NUMBER() OVER (ORDER BY points DESC) as rank
                    FROM leaderboard 
                    WHERE guild_id = $1
                    ORDER BY points DESC
                ''', guild_id)

                # Filter out users who are no longer in the server
                filtered_data = []
                for row in all_rows:
                    user_id = row['user_id']
                    
                    # Check if user is still in the guild (only if bot and guild are available)
                    if guild:
                        try:
                            user_id_int = int(user_id) if isinstance(user_id, str) else user_id
                            member = guild.get_member(user_id_int)
                            if not member:
                                # User no longer in server, skip this entry
                                continue
                        except (ValueError, TypeError):
                            # Invalid user ID, skip
                            continue
                    
                    entry = {
                        'user_id': row['user_id'],
                        'username': row['username'],
                        'points': row['points'],
                        'last_updated': row['last_updated'],
                        'created_at': row['created_at']
                    }
                    filtered_data.append(entry)

                # Recalculate ranks after filtering
                for i, entry in enumerate(filtered_data):
                    entry['rank'] = i + 1

                # Calculate pagination after filtering
                total_count = len(filtered_data)
                total_pages = max(1, (total_count + per_page - 1) // per_page)
                
                # Apply pagination to filtered data
                offset = (page - 1) * per_page
                leaderboard_data = filtered_data[offset:offset + per_page]

                return leaderboard_data, page, total_pages

        except asyncpg_exceptions.ConnectionDoesNotExistError as e:
            logger.error(f"❌ Database connection error getting leaderboard: {e}")
            return [], 1, 1
        except Exception as e:
            logger.error(f"❌ Error getting leaderboard: {e}")
            return [], 1, 1

    async def get_top_users(self, guild_id: int, limit: int = 10) -> List[Dict]:
        """Get top users by points, filtering out users no longer in the server"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return []
        try:
            # Get guild instance to check member existence
            guild = None
            if self.bot:
                guild = self.bot.get_guild(guild_id)
                
            async with self.database.pool.acquire() as conn:
                # Get all users first, then filter and limit
                rows = await conn.fetch('''
                    SELECT *, 
                           ROW_NUMBER() OVER (ORDER BY points DESC) as rank
                    FROM leaderboard 
                    WHERE guild_id = $1
                    ORDER BY points DESC
                ''', guild_id)

                filtered_users = []
                for row in rows:
                    user_id = row['user_id']
                    
                    # Check if user is still in the guild (only if bot and guild are available)
                    if guild:
                        try:
                            user_id_int = int(user_id) if isinstance(user_id, str) else user_id
                            member = guild.get_member(user_id_int)
                            if not member:
                                # User no longer in server, skip this entry
                                continue
                        except (ValueError, TypeError):
                            # Invalid user ID, skip
                            continue
                    
                    user = {
                        'user_id': row['user_id'],
                        'username': row['username'],
                        'points': row['points'],
                        'last_updated': row['last_updated']
                    }
                    filtered_users.append(user)
                    
                    # Stop when we reach the desired limit
                    if len(filtered_users) >= limit:
                        break

                # Recalculate ranks after filtering
                for i, user in enumerate(filtered_users):
                    user['rank'] = i + 1

                return filtered_users

        except asyncpg_exceptions.ConnectionDoesNotExistError as e:
            logger.error(f"❌ Database connection error getting top users: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Error getting top users: {e}")
            return []

    async def is_mentor_cached(self, user_id: int, guild_id: int) -> bool:
        """Check if user is a mentor with caching"""
        try:
            import time
            cache_key = f"{user_id}_{guild_id}"
            current_time = time.time()

            # Check if we have a cached result that's still fresh
            if (cache_key in self._mentor_cache and 
                cache_key in self._cache_timestamp and
                current_time - self._cache_timestamp[cache_key] < self._cache_duration):
                return self._mentor_cache[cache_key]

            # Cache miss or expired, fetch from database
            if not self.database.pool:
                logger.error("❌ Database pool not initialized")
                return False
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchval('''
                    SELECT COUNT(*) FROM mentors 
                    WHERE user_id = $1 AND guild_id = $2 AND is_active = TRUE
                ''', user_id, guild_id)

                is_mentor = result > 0

                # Cache the result
                self._mentor_cache[cache_key] = is_mentor
                self._cache_timestamp[cache_key] = current_time

                return is_mentor

        except Exception as e:
            logger.error(f"❌ Error checking cached mentor status: {e}")
            return False

    def invalidate_mentor_cache(self, user_id: Optional[int] = None, guild_id: Optional[int] = None):
        """Invalidate mentor cache for specific user or entire guild"""
        if user_id and guild_id:
            cache_key = f"{user_id}_{guild_id}"
            self._mentor_cache.pop(cache_key, None)
            self._cache_timestamp.pop(cache_key, None)
        elif guild_id:
            # Invalidate all entries for this guild
            keys_to_remove = [key for key in self._mentor_cache.keys() if key.endswith(f"_{guild_id}")]
            for key in keys_to_remove:
                self._mentor_cache.pop(key, None)
                self._cache_timestamp.pop(key, None)
        else:
            # Clear entire cache
            self._mentor_cache.clear()
            self._cache_timestamp.clear()

    async def get_guild_statistics(self, guild_id: int) -> Dict:
        """Get comprehensive guild statistics"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return {
                'guild_id': guild_id,
                'total_members': 0,
                'total_points': 0,
                'average_points': 0.0,
                'highest_points': 0,
                'total_quests_completed': 0,
                'total_quests_accepted': 0,
                'total_quests_rejected': 0
            }
        try:
            async with self.database.pool.acquire() as conn:
                # Get leaderboard stats
                leaderboard_stats = await conn.fetchrow('''
                    SELECT 
                        COUNT(*) as total_members,
                        COALESCE(SUM(points), 0) as total_points,
                        COALESCE(AVG(points), 0) as average_points,
                        COALESCE(MAX(points), 0) as highest_points
                    FROM leaderboard 
                    WHERE guild_id = $1
                ''', guild_id)

                # Get quest stats
                quest_stats = await conn.fetchrow('''
                    SELECT 
                        COALESCE(SUM(quests_completed), 0) as total_completed,
                        COALESCE(SUM(quests_accepted), 0) as total_accepted,
                        COALESCE(SUM(quests_rejected), 0) as total_rejected
                    FROM user_stats 
                    WHERE guild_id = $1
                ''', guild_id)

                stats = {
                    'guild_id': guild_id,
                    'total_members': leaderboard_stats['total_members'] or 0,
                    'total_points': leaderboard_stats['total_points'] or 0,
                    'average_points': float(leaderboard_stats['average_points'] or 0),
                    'highest_points': leaderboard_stats['highest_points'] or 0,
                    'total_quests_completed': quest_stats['total_completed'] if quest_stats else 0,
                    'total_quests_accepted': quest_stats['total_accepted'] if quest_stats else 0,
                    'total_quests_rejected': quest_stats['total_rejected'] if quest_stats else 0
                }

                return stats

        except Exception as e:
            logger.error(f"❌ Error getting guild statistics: {e}")
            return {
                'guild_id': guild_id,
                'total_members': 0,
                'total_points': 0,
                'average_points': 0.0,
                'highest_points': 0,
                'total_quests_completed': 0,
                'total_quests_accepted': 0,
                'total_quests_rejected': 0
            }

    async def update_user_quest_stats(self, guild_id: int, user_id: int, username: str, 
                                     quest_completed: bool = False, quest_accepted: bool = False, 
                                     quest_rejected: bool = False):
        """Update user quest statistics"""
        try:
            # Ensure user exists in leaderboard first
            await self.add_member(guild_id, user_id, username)

            if not self.database.pool:
                logger.error("❌ Database pool not initialized")
                return
            async with self.database.pool.acquire() as conn:
                # Get current stats
                current_stats = await conn.fetchrow('''
                    SELECT * FROM user_stats WHERE guild_id = $1 AND user_id = $2
                ''', guild_id, user_id)

                if current_stats:
                    # Update existing stats
                    new_completed = current_stats['quests_completed'] + (1 if quest_completed else 0)
                    new_accepted = current_stats['quests_accepted'] + (1 if quest_accepted else 0)
                    new_rejected = current_stats['quests_rejected'] + (1 if quest_rejected else 0)

                    await conn.execute('''
                        UPDATE user_stats 
                        SET quests_completed = $3, quests_accepted = $4, quests_rejected = $5,
                            last_updated = CURRENT_TIMESTAMP
                        WHERE guild_id = $1 AND user_id = $2
                    ''', guild_id, user_id, new_completed, new_accepted, new_rejected)
                else:
                    # Create new stats entry
                    await conn.execute('''
                        INSERT INTO user_stats (guild_id, user_id, quests_completed, quests_accepted, quests_rejected, last_updated)
                        VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                    ''', guild_id, user_id, 
                        1 if quest_completed else 0,
                        1 if quest_accepted else 0,
                        1 if quest_rejected else 0)

                logger.info(f"✅ Updated quest stats for {username} in guild {guild_id}")

        except Exception as e:
            logger.error(f"❌ Error updating quest stats for {username}: {e}")

    async def award_quest_points(self, guild_id: int, user_id: int, username: str, points: int, quest_id: str):
        """Award points for quest completion and update quest stats"""
        try:
            # Update points in leaderboard
            success = await self.update_points(guild_id, user_id, points, username)

            if success:
                # Update quest completion stats
                await self.update_user_quest_stats(guild_id, user_id, username, quest_completed=True)
                logger.info(f"✅ Awarded {points} points to {username} for quest {quest_id}")
                return True
            else:
                logger.error(f"❌ Failed to award points to {username} for quest {quest_id}")
                return False

        except Exception as e:
            logger.error(f"❌ Error awarding quest points: {e}")
            return False

    async def get_user_rank(self, guild_id: int, user_id: int) -> Optional[int]:
        """Get user's rank in the guild"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return None
        try:
            async with self.database.pool.acquire() as conn:
                rank = await conn.fetchval('''
                    SELECT rank FROM (
                        SELECT user_id, ROW_NUMBER() OVER (ORDER BY points DESC) as rank
                        FROM leaderboard 
                        WHERE guild_id = $1
                    ) ranked
                    WHERE user_id = $2
                ''', guild_id, user_id)
                return rank
        except Exception as e:
            logger.error(f"❌ Error getting user rank: {e}")
            return None

    async def search_users(self, guild_id: int, username_query: str, limit: int = 10) -> List[Dict]:
        """Search users by username"""
        if not self.database.pool:
            logger.error("❌ Database pool not initialized")
            return []
        try:
            async with self.database.pool.acquire() as conn:
                rows = await conn.fetch('''
                    SELECT *, 
                           ROW_NUMBER() OVER (ORDER BY points DESC) as rank
                    FROM leaderboard 
                    WHERE guild_id = $1 AND LOWER(username) LIKE LOWER($2)
                    ORDER BY points DESC
                    LIMIT $3
                ''', guild_id, f'%{username_query}%', limit)

                users = []
                for row in rows:
                    user = {
                        'rank': row['rank'],
                        'user_id': row['user_id'],
                        'username': row['username'],
                        'points': row['points'],
                        'last_updated': row['last_updated']
                    }
                    users.append(user)

                return users

        except Exception as e:
            logger.error(f"❌ Error searching users: {e}")
            return []