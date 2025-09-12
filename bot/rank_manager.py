import discord
import asyncio
import asyncpg
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from bot.utils import SPECIAL_ROLES, create_error_embed, create_success_embed


class RankManager:
    def __init__(self, db):
        self.db = db
        self.high_rank_roles = list(SPECIAL_ROLES.keys())
        self.role_names = SPECIAL_ROLES
        self._initialized = False
    
    async def initialize_tables(self):
        """Initialize required database tables"""
        if self._initialized:
            return
            
        try:
            async with self.db.pool.acquire() as conn:
                # Create role_limits table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS role_limits (
                        guild_id BIGINT,
                        role_id BIGINT,
                        member_limit INTEGER,
                        PRIMARY KEY (guild_id, role_id)
                    )
                ''')
                
                # Create role_assignments table  
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS role_assignments (
                        guild_id BIGINT,
                        user_id BIGINT,
                        role_id BIGINT,
                        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (guild_id, user_id, role_id)
                    )
                ''')
                
                # Create hr_activity_log table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS hr_activity_log (
                        id SERIAL PRIMARY KEY,
                        guild_id BIGINT,
                        user_id BIGINT,
                        role_id BIGINT,
                        action VARCHAR(20),
                        reason VARCHAR(50),
                        moderator_id BIGINT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Add moderator_id column if it doesn't exist (for existing databases)
                try:
                    await conn.execute('''
                        ALTER TABLE hr_activity_log 
                        ADD COLUMN IF NOT EXISTS moderator_id BIGINT
                    ''')
                except:
                    pass  # Column might already exist
                
                # Create hr_live_monitor table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS hr_live_monitor (
                        guild_id BIGINT PRIMARY KEY,
                        channel_id BIGINT,
                        message_id BIGINT
                    )
                ''')
            
            self._initialized = True
            print("✅ Rank manager database tables initialized")
            
        except Exception as e:
            print(f"❌ Error initializing rank manager tables: {e}")
            raise
        
    async def set_role_limit(self, guild_id: int, role_id: int, limit: int) -> bool:
        """Set member limit for a role"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO role_limits (guild_id, role_id, member_limit) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (guild_id, role_id) 
                       DO UPDATE SET member_limit = $3""",
                    guild_id, role_id, limit
                )
            return True
        except Exception as e:
            print(f"Error setting role limit: {e}")
            return False
    
    async def get_role_limit(self, guild_id: int, role_id: int) -> Optional[int]:
        """Get member limit for a role"""
        try:
            async with self.db.pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT member_limit FROM role_limits WHERE guild_id = $1 AND role_id = $2",
                    guild_id, role_id
                )
            return result
        except Exception:
            return None
    
    async def get_all_role_limits(self, guild_id: int) -> Dict[int, int]:
        """Get all role limits for a guild"""
        try:
            async with self.db.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT role_id, member_limit FROM role_limits WHERE guild_id = $1",
                    guild_id
                )
            return {row['role_id']: row['member_limit'] for row in rows}
        except Exception:
            return {}
    
    async def remove_role_limit(self, guild_id: int, role_id: int) -> bool:
        """Remove limit for a role"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM role_limits WHERE guild_id = $1 AND role_id = $2",
                    guild_id, role_id
                )
            return True
        except Exception:
            return False
    
    async def track_role_assignment(self, guild_id: int, user_id: int, role_id: int):
        """Track when a role is assigned to a user"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO role_assignments (guild_id, user_id, role_id) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (guild_id, user_id, role_id) 
                       DO UPDATE SET assigned_at = CURRENT_TIMESTAMP""",
                    guild_id, user_id, role_id
                )
        except Exception as e:
            print(f"Error tracking role assignment: {e}")
    
    async def remove_role_assignment(self, guild_id: int, user_id: int, role_id: int):
        """Remove role assignment tracking"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM role_assignments WHERE guild_id = $1 AND user_id = $2 AND role_id = $3",
                    guild_id, user_id, role_id
                )
        except Exception as e:
            print(f"Error removing role assignment: {e}")
    
    async def get_newest_role_holder(self, guild_id: int, role_id: int) -> Optional[int]:
        """Get the user who most recently got this role"""
        try:
            async with self.db.pool.acquire() as conn:
                result = await conn.fetchval(
                    """SELECT user_id FROM role_assignments 
                       WHERE guild_id = $1 AND role_id = $2 
                       ORDER BY assigned_at DESC LIMIT 1""",
                    guild_id, role_id
                )
            return result
        except Exception:
            return None
    
    async def get_role_holders_count(self, guild: discord.Guild, role_id: int) -> int:
        """Get current number of members with this role"""
        role = guild.get_role(role_id)
        if not role:
            return 0
        return len(role.members)
    
    async def log_hr_activity(self, guild_id: int, user_id: int, role_id: int, action: str, reason: str, moderator_id: int = None):
        """Log high rank activity for live monitoring"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO hr_activity_log (guild_id, user_id, role_id, action, reason, moderator_id) 
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    guild_id, user_id, role_id, action, reason, moderator_id
                )
        except Exception as e:
            print(f"Error logging HR activity: {e}")
    
    async def get_recent_hr_activity(self, guild_id: int, limit: int = 10) -> List[Dict]:
        """Get recent high rank activity"""
        try:
            async with self.db.pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT user_id, role_id, action, reason, moderator_id, timestamp 
                       FROM hr_activity_log 
                       WHERE guild_id = $1 
                       ORDER BY timestamp DESC 
                       LIMIT $2""",
                    guild_id, limit
                )
            return [dict(row) for row in rows]
        except Exception:
            return []
    
    async def set_live_monitor(self, guild_id: int, channel_id: int, message_id: int):
        """Set live monitor location"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO hr_live_monitor (guild_id, channel_id, message_id) 
                       VALUES ($1, $2, $3) 
                       ON CONFLICT (guild_id) 
                       DO UPDATE SET channel_id = $2, message_id = $3""",
                    guild_id, channel_id, message_id
                )
        except Exception as e:
            print(f"Error setting live monitor: {e}")
    
    async def get_live_monitor(self, guild_id: int) -> Optional[Tuple[int, int]]:
        """Get live monitor location"""
        try:
            async with self.db.pool.acquire() as conn:
                result = await conn.fetchrow(
                    "SELECT channel_id, message_id FROM hr_live_monitor WHERE guild_id = $1",
                    guild_id
                )
            if result:
                return result['channel_id'], result['message_id']
            return None
        except Exception:
            return None
    
    async def remove_live_monitor(self, guild_id: int):
        """Remove live monitor"""
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM hr_live_monitor WHERE guild_id = $1",
                    guild_id
                )
        except Exception as e:
            print(f"Error removing live monitor: {e}")
    
    async def enforce_role_limit(self, guild: discord.Guild, role_id: int, exclude_user_id: int = None):
        """Enforce role limit by removing newest member if over limit"""
        try:
            # Ensure tables are initialized
            if not self._initialized:
                await self.initialize_tables()
                
            limit = await self.get_role_limit(guild.id, role_id)
            if not limit:
                return
            
            current_count = await self.get_role_holders_count(guild, role_id)
            if current_count <= limit:
                return
            
            # Get newest role holder (excluding the user who just got the role)
            newest_user_id = await self.get_newest_role_holder_excluding(guild.id, role_id, exclude_user_id)
            if not newest_user_id:
                return
            
            member = guild.get_member(newest_user_id)
            role = guild.get_role(role_id)
            if member and role:
                try:
                    await member.remove_roles(role, reason="Role limit exceeded - removed newest member")
                    await self.remove_role_assignment(guild.id, newest_user_id, role_id)
                    await self.log_hr_activity(guild.id, newest_user_id, role_id, "REMOVED", "LIMIT_EXCEEDED")
                    print(f"✅ Role limit enforced: Removed {member.display_name} from {role.name}")
                    return member
                except discord.Forbidden:
                    print(f"❌ Cannot enforce role limit for {role.name}: Bot lacks permission to remove roles")
                    return None
                except discord.HTTPException as e:
                    print(f"❌ HTTP error enforcing role limit for {role.name}: {e}")
                    return None
        except Exception as e:
            print(f"❌ Error enforcing role limit: {e}")
        return None
    
    async def get_newest_role_holder_excluding(self, guild_id: int, role_id: int, exclude_user_id: int = None) -> Optional[int]:
        """Get the user who most recently got this role, excluding a specific user"""
        try:
            async with self.db.pool.acquire() as conn:
                if exclude_user_id:
                    result = await conn.fetchval(
                        """SELECT user_id FROM role_assignments 
                           WHERE guild_id = $1 AND role_id = $2 AND user_id != $3
                           ORDER BY assigned_at DESC LIMIT 1""",
                        guild_id, role_id, exclude_user_id
                    )
                else:
                    result = await conn.fetchval(
                        """SELECT user_id FROM role_assignments 
                           WHERE guild_id = $1 AND role_id = $2 
                           ORDER BY assigned_at DESC LIMIT 1""",
                        guild_id, role_id
                    )
            return result
        except Exception:
            return None
    
    def is_high_rank_role(self, role_id: int) -> bool:
        """Check if role is a high rank role"""
        return role_id in self.high_rank_roles
    
    def get_high_rank_roles_for_guild(self, guild: discord.Guild) -> List[discord.Role]:
        """Get all high rank roles that exist in the guild"""
        roles = []
        for role_id in self.high_rank_roles:
            role = guild.get_role(role_id)
            if role:
                roles.append(role)
        return roles